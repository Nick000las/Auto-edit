
import os
from dotenv import load_dotenv
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=dotenv_path)

import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import transcribe
import process
import video_editor
import subtitles
from utils import run_ffmpeg_command, get_video_duration, check_ffmpeg_paths

VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv')


class VideoHandler(FileSystemEventHandler):
    def __init__(self, ffmpeg_path: str, ffprobe_path: str):
        super().__init__()
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        print("[HANDLER INICIADO] Caminhos do FFmpeg configurados.")

    def on_created(self, event):
        if event.is_directory:
            return

        filepath = event.src_path

        if filepath.lower().endswith(VIDEO_EXTENSIONS):
            print(f"[NOVO VÍDEO DETECTADO] {filepath}")

            # Pausa para garantir que o arquivo foi completamente copiado.
            # Uma abordagem mais robusta poderia verificar a estabilidade do tamanho do arquivo.
            time.sleep(2)
            # Passa os caminhos dos executáveis para a função de processamento
            process_video(filepath, self.ffmpeg_path, self.ffprobe_path)


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
    
    nome_arquivo = os.path.basename(filepath)
    nome_base, extensao = os.path.splitext(nome_arquivo)
    
    # Define os caminhos dos arquivos temporários e finais
    caminho_audio_temp = os.path.join("temp", f"{nome_base}.mp3")
    caminho_video_editado_temp = os.path.join("temp", f"{nome_base}_editado.mp4")
    caminho_srt_temp = os.path.join("temp", f"{nome_base}.srt")
    caminho_video_final_output = os.path.join("output_videos", f"{nome_base}_final.mp4")

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
        
        # Prepara os segmentos para a próxima etapa
        segmentos_whisper = [
            {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
            for seg in transcricao.segments
        ]
        
        print("\n--- TRANSCRIÇÃO BRUTA RECEBIDA ---")
        for seg in segmentos_whisper:
            print(f"[{seg['start']:05.2f} - {seg['end']:05.2f}] {seg['text']}")

        # Etapa 3: Análise Semântica com IA para identificar trechos úteis
        segmentos_uteis = process.refinar_transcricao_com_ia(segmentos_whisper)
        
        print("\n--- SEGMENTOS ÚTEIS (IA) ---")
        print(segmentos_uteis)

        # Etapa 4: Detecção e remoção de silêncios
        silencios_detectados = process.detect_silences(filepath, ffmpeg_path)
        segmentos_nao_silenciosos = process.generate_non_silent_segments(video_duration, silencios_detectados)
        
        print("\n--- SEGMENTOS NÃO-SILENCIOSOS ---")
        print(segmentos_nao_silenciosos)

        # Etapa 5: Mapeamento de Cortes (Interseção)
        segmentos_finais_para_corte = process.merge_segments(segmentos_uteis, segmentos_nao_silenciosos)
        
        print("\n--- SEGMENTOS FINAIS PARA CORTE (IA + Não-Silêncio) ---")
        print(segmentos_finais_para_corte)

        # Etapa 6: Edição e Concatenação (gera vídeo temporário)
        sucesso_edicao = video_editor.cortar_e_concatenar(
            caminho_video_original=filepath,
            segmentos_finais=segmentos_finais_para_corte,
            caminho_saida=caminho_video_editado_temp,
            ffmpeg_path=ffmpeg_path
        )

        if not sucesso_edicao:
            print("[ERRO] Falha na etapa de edição do vídeo. Abortando.")
            return

        # Etapa 7: Geração de Legendas (.srt)
        subtitles.gerar_srt(
            transcricao_original=segmentos_whisper,
            segmentos_finais=segmentos_finais_para_corte,
            caminho_srt=caminho_srt_temp
        )

        # Etapa 8: Embutir Legendas no Vídeo (Hardcode)
        subtitles.embutir_legendas(
            caminho_video_temp=caminho_video_editado_temp,
            caminho_srt=caminho_srt_temp,
            caminho_video_final=caminho_video_final_output,
            ffmpeg_path=ffmpeg_path
        )

    except Exception as e:
        print(f"Ocorreu um erro inesperado ao processar {filepath}: {e}")
    finally:
        # Etapa 9: Limpeza de arquivos temporários
        print("[LIMPEZA] Removendo arquivos temporários...")
        arquivos_para_limpar = [caminho_audio_temp, caminho_video_editado_temp, caminho_srt_temp]
        for arquivo in arquivos_para_limpar:
            try:
                if os.path.exists(arquivo):
                    os.remove(arquivo)
                    print(f" - Removido: {arquivo}")
            except OSError as e:
                print(f" - Erro ao remover {arquivo}: {e}")

def start_watchdog(path: str, ffmpeg_path: str, ffprobe_path: str):
    event_handler = VideoHandler(ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path)
    observer = Observer()
    observer.schedule(event_handler, path=path, recursive=False)

    observer.start()
    print(f"[MONITORANDO] Pasta: {path}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("[PARADO] Watchdog encerrado.")

    observer.join()


if __name__ == "__main__":
    # HARDCODED: Caminhos para FFmpeg e FFprobe (para resolver o problema de carregamento do .env)
    # Lembre-se de que esta é uma solução temporária. O ideal é usar o .env.
    FFMPEG_PATH = "D:/ffmpeg/ffmpeg-8.1-essentials_build/bin/ffmpeg.exe"
    FFPROBE_PATH = "D:/ffmpeg/ffmpeg-8.1-essentials_build/bin/ffprobe.exe"
    
    print(f"FFMPEG_PATH: {FFMPEG_PATH}")
    print(f"FFPROBE_PATH: {FFPROBE_PATH}")

    # Verificação inicial para garantir que o FFmpeg está configurado corretamente
    check_ffmpeg_paths(ffmpeg_path=FFMPEG_PATH, ffprobe_path=FFPROBE_PATH)
    
    # Inicia o monitoramento da pasta, passando os caminhos para o handler
    start_watchdog(path="input_videos", ffmpeg_path=FFMPEG_PATH, ffprobe_path=FFPROBE_PATH)