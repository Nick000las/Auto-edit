
import os
from dotenv import load_dotenv
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=dotenv_path)

import time
import queue
import concurrent.futures
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import transcribe
import process
import video_editor
import subtitles
from utils import run_ffmpeg_command, get_video_duration, check_ffmpeg_paths, aguardar_arquivo_estabilizar

VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv')

# Fila para o padrão Produtor-Consumidor
video_queue = queue.Queue()


class VideoHandler(FileSystemEventHandler):
    """Produtor: Detecta novos vídeos e os adiciona a uma fila de processamento."""
    def __init__(self, processing_queue: queue.Queue):
        super().__init__()
        self.queue = processing_queue
        print("[PRODUTOR] Handler do Watchdog iniciado.")

    def on_created(self, event):
        if event.is_directory:
            return

        filepath = event.src_path

        if filepath.lower().endswith(VIDEO_EXTENSIONS):
            print(f"[PRODUTOR] Novo vídeo detectado: {os.path.basename(filepath)}. Adicionando à fila.")
            self.queue.put(filepath)


def extrair_audio(caminho_video: str, caminho_saida_audio: str, ffmpeg_path: str):
    """Extrai o áudio de um arquivo de vídeo usando FFmpeg."""
    print(f"Extraindo áudio de '{caminho_video}'...")
    comando = [
        ffmpeg_path,
        '-i', caminho_video,
        '-vn',  # Sem vídeo
        '-acodec', 'libmp3lame',  # Codec de áudio MP3
        '-q:a', '2',  # Qualidade do áudio (0-9, 0 é a melhor)
        '-y',  # Sobrescrever arquivo de saída se existir
        caminho_saida_audio
    ]
    try:
        run_ffmpeg_command(comando)
        print(f"Áudio extraído com sucesso para '{caminho_saida_audio}'")
        return True
    except Exception: # A exceção específica já é tratada e impressa dentro de run_ffmpeg_command
        return False


def process_video(filepath: str, ffmpeg_path: str, ffprobe_path: str):
    """
    Executa o pipeline de processamento para um único vídeo.
    """
    print(f"[PROCESSANDO] {filepath}")
    
    # Garante que os diretórios temporário e de saída existem
    os.makedirs("temp", exist_ok=True)
    os.makedirs("output_videos", exist_ok=True)
    os.makedirs("input_videos", exist_ok=True)

    
    nome_arquivo = os.path.basename(filepath)
    nome_base, extensao = os.path.splitext(nome_arquivo)
    
    # Define os caminhos dos arquivos temporários e finais
    caminho_audio_temp = os.path.join("temp", f"{nome_base}.mp3")
    caminho_ass_temp = os.path.join("temp", f"{nome_base}.ass")
    caminho_video_final = os.path.join("output_videos", f"{nome_base}_final.mp4")

    # Etapa 0: Obter duração total do vídeo
    video_duration = get_video_duration(filepath, ffprobe_path)
    print(f"Duração do vídeo: {video_duration:.2f} segundos")

    try:
        # Etapa 1: Extrair áudio do vídeo
        if not extrair_audio(filepath, caminho_audio_temp, ffmpeg_path):
            return # Pula para o próximo se a extração falhar

        # VERIFICAÇÃO DE TAMANHO PARA DEBUG: Verifica o tamanho do áudio extraído.
        tamanho_audio_mb = os.path.getsize(caminho_audio_temp) / (1024 * 1024)
        print(f"[DEBUG] Tamanho do arquivo de áudio: {tamanho_audio_mb:.2f} MB")
        if tamanho_audio_mb > 24: # Limite da API do Whisper é 25MB, usamos 24 como margem de segurança.
            print("[AVISO] O arquivo de áudio pode exceder o limite de 25MB da API do Whisper.")

        # Etapa 2: Transcrição com Whisper
        transcricao = transcribe.transcrever_com_whisper(caminho_audio_temp)
        
        # Verificação de segurança: Se a transcrição falhar, interrompe o processo para este vídeo.
        if transcricao is None:
            print("[ERRO] A etapa de transcrição falhou. Abortando o processamento deste vídeo.")
            return

        # Verificação de robustez: Garante que a resposta da API contém os dados esperados.
        if not hasattr(transcricao, 'segments') or not hasattr(transcricao, 'words'):
            print("[ERRO] A resposta da API de transcrição não continha a estrutura esperada (segments/words). Abortando.")
            print(f"   Resposta recebida: {transcricao}")
            return

        # Prepara os dados da transcrição para a IA.
        # Se a API não retornar segmentos, cria um único segmento com o texto completo.
        if transcricao.segments:
            segmentos_whisper = [
                {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
                for seg in transcricao.segments
            ]
        else:
            print("[AVISO] A API não retornou segmentos. Criando um segmento único com o texto completo para análise da IA.")
            segmentos_whisper = [{
                "start": 0, "end": transcricao.duration, "text": transcricao.text
            }]
        palavras_transcritas = [
            {"word": p.word, "start": p.start, "end": p.end}
            for p in transcricao.words
        ]
        
        print(f"\n--- TRANSCRIÇÃO BRUTA RECEBIDA ---\n\"{transcricao.text}\"")

        # Etapa 3: Análise Semântica com IA para identificar trechos úteis
        texto_limpo_ia = process.refinar_transcricao_com_ia(transcricao.text)
        
        # Verificação de segurança: Se a IA falhar, interrompe o processo para este vídeo.
        if texto_limpo_ia is None:
            print("[ERRO] A análise da IA falhou ou retornou uma resposta vazia. Abortando o processamento deste vídeo.")
            return

        # Etapa 3.5: Alinhar texto limpo com palavras originais para obter timestamps
        intervalos_permitidos_ia = process.alinhar_texto_com_palavras(texto_limpo_ia, palavras_transcritas)
        print(f"\n--- INTERVALOS PERMITIDOS (IA - Pós-Alinhamento) ---")
        print(intervalos_permitidos_ia)

        # Etapa 4: Filtragem de Palavras
        # Apenas as palavras que estão dentro dos intervalos aprovados pela IA serão usadas
        palavras_filtradas = process.filtrar_palavras_por_intervalos(palavras_transcritas, intervalos_permitidos_ia)
        print(f"\n--- PALAVRAS FILTRADAS ({len(palavras_filtradas)} de {len(palavras_transcritas)}) ---")

        # Etapa 5: Detecção e remoção de silêncios
        silencios_detectados = process.detect_silences(filepath, ffmpeg_path)
        segmentos_nao_silenciosos = process.generate_non_silent_segments(video_duration, silencios_detectados)
        
        print("\n--- SEGMENTOS NÃO-SILENCIOSOS ---")
        print(segmentos_nao_silenciosos)

        # Etapa 6: Mapeamento de Cortes (Interseção)
        # Cruza os intervalos permitidos pela IA com os intervalos não-silenciosos
        segmentos_finais_para_corte = process.merge_segments(intervalos_permitidos_ia, segmentos_nao_silenciosos)
        
        print("\n--- SEGMENTOS FINAIS PARA CORTE (IA + Não-Silêncio) ---")
        print(segmentos_finais_para_corte)

        # Verificação de segurança: Se não houver segmentos válidos após o merge, não há o que editar.
        if not segmentos_finais_para_corte:
            print("[AVISO] Nenhum segmento válido encontrado para edição após cruzar dados da IA e silêncio. Abortando.")
            return

        # Etapa 7: Geração de Legendas (.ass) - Agora ANTES da edição do vídeo
        subtitles.gerar_ass(
            lista_palavras_transcritas=palavras_filtradas, # Usa as palavras já filtradas pela IA
            segmentos_finais=segmentos_finais_para_corte,
            caminho_ass=caminho_ass_temp
        )

        # Etapa 8: Edição e Legendagem em Passo Único (Single-Pass Encoding)
        sucesso_final = video_editor.editar_e_legendar_em_passo_unico(
            caminho_video_original=filepath,
            segmentos_finais=segmentos_finais_para_corte,
            caminho_ass=caminho_ass_temp,
            caminho_saida=caminho_video_final,
            ffmpeg_path=ffmpeg_path
        )

        if not sucesso_final:
            print("[ERRO] Falha na etapa de edição e legendagem do vídeo. Abortando.")
            return

    except Exception as e:
        print(f"Ocorreu um erro inesperado ao processar {filepath}: {e}")
    finally:
        # Etapa Final: Limpeza de arquivos temporários
        print("[LIMPEZA] Removendo arquivos temporários...")
        arquivos_para_limpar = [caminho_audio_temp, caminho_ass_temp]
        for arquivo in arquivos_para_limpar:
            try:
                if os.path.exists(arquivo):
                    os.remove(arquivo)
                    print(f" - Removido: {arquivo}")
            except OSError as e:
                print(f" - Erro ao remover {arquivo}: {e}")

def consumer_worker(processing_queue: queue.Queue, ffmpeg_path: str, ffprobe_path: str):
    """Consumidor: Pega vídeos da fila e os processa um por um."""
    print("[CONSUMIDOR] Worker iniciado. Aguardando vídeos na fila...")
    while True:
        try:
            filepath = processing_queue.get()
            print(f"\n[CONSUMIDOR] Pegou '{os.path.basename(filepath)}' da fila para processar.")

            # PASSO 1: Aguarda o arquivo estabilizar antes de qualquer coisa
            if aguardar_arquivo_estabilizar(filepath):
                print(f"[CONSUMIDOR] Arquivo '{os.path.basename(filepath)}' estabilizado. Iniciando processamento.")
                process_video(filepath, ffmpeg_path, ffprobe_path)
            else:
                print(f"[CONSUMIDOR] Falha ao estabilizar o arquivo '{os.path.basename(filepath)}'. Pulando.")
            
            processing_queue.task_done()
        except Exception as e:
            print(f"[CONSUMIDOR] Erro inesperado no worker: {e}")

def start_processing_system(path: str, ffmpeg_path: str, ffprobe_path: str):
    """Inicia o sistema de produtor (watchdog) e consumidor (worker)."""
    # Inicia o worker consumidor em uma thread separada com no máximo 1 worker
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    executor.submit(consumer_worker, video_queue, ffmpeg_path, ffprobe_path)

    # Inicia o produtor (watchdog) na thread principal
    event_handler = VideoHandler(processing_queue=video_queue)
    observer = Observer()
    observer.schedule(event_handler, path=path, recursive=False)

    observer.start()
    print(f"[MONITORANDO] Pasta: {path}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SISTEMA] Interrupção recebida. Encerrando...")
        observer.stop()

    observer.join()
    executor.shutdown(wait=False, cancel_futures=True) # Encerra o executor
    print("[SISTEMA] Encerrado.")


if __name__ == "__main__":
    # HARDCODED: Caminhos para FFmpeg e FFprobe (para resolver o problema de carregamento do .env)
    # Lembre-se de que esta é uma solução temporária. O ideal é usar o .env.
    FFMPEG_PATH = "D:/ffmpeg/ffmpeg-8.1-essentials_build/bin/ffmpeg.exe"
    FFPROBE_PATH = "D:/ffmpeg/ffmpeg-8.1-essentials_build/bin/ffprobe.exe"
    
    print(f"FFMPEG_PATH: {FFMPEG_PATH}")
    print(f"FFPROBE_PATH: {FFPROBE_PATH}")

    # Verificação inicial para garantir que o FFmpeg está configurado corretamente
    check_ffmpeg_paths(ffmpeg_path=FFMPEG_PATH, ffprobe_path=FFPROBE_PATH)
    
    # Inicia o sistema de monitoramento e processamento
    start_processing_system(path="input_videos", ffmpeg_path=FFMPEG_PATH, ffprobe_path=FFPROBE_PATH)