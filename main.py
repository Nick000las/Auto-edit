import time
import os
import subprocess
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import transcribe
import process

VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv')


class VideoHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return

        filepath = event.src_path

        if filepath.lower().endswith(VIDEO_EXTENSIONS):
            print(f"[NOVO VÍDEO DETECTADO] {filepath}")

            # Pausa para garantir que o arquivo foi completamente copiado.
            # Uma abordagem mais robusta poderia verificar a estabilidade do tamanho do arquivo.
            time.sleep(2)

            process_video(filepath)


def extrair_audio(caminho_video, caminho_saida_audio):
    """Extrai o áudio de um arquivo de vídeo usando FFmpeg."""
    print(f"Extraindo áudio de '{caminho_video}'...")
    try:
        comando = [
            'ffmpeg',
            '-i', caminho_video,
            '-vn',  # Sem vídeo
            '-acodec', 'libmp3lame',  # Codec de áudio MP3
            '-q:a', '2',  # Qualidade do áudio (0-9, 0 é a melhor)
            '-y',  # Sobrescrever arquivo de saída se existir
            caminho_saida_audio
        ]
        subprocess.run(comando, check=True, capture_output=True, text=True)
        print(f"Áudio extraído com sucesso para '{caminho_saida_audio}'")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Erro ao extrair áudio com FFmpeg: {e.stderr}")
        return False
    except FileNotFoundError:
        print("Erro: FFmpeg não encontrado. Verifique se ele está instalado e no PATH do sistema.")
        return False


def process_video(filepath):
    """
    Executa o pipeline de processamento para um único vídeo.
    """
    print(f"[PROCESSANDO] {filepath}")
    
    # Garante que o diretório temporário existe
    os.makedirs("temp", exist_ok=True)
    
    nome_arquivo = os.path.basename(filepath)
    caminho_audio_temp = os.path.join("temp", f"{os.path.splitext(nome_arquivo)[0]}.mp3")

    try:
        # 1. Extrair áudio do vídeo
        if not extrair_audio(filepath, caminho_audio_temp):
            return # Pula para o próximo se a extração falhar

        # 2. Transcrição com Whisper
        transcricao = transcribe.transcrever_com_whisper(caminho_audio_temp)
        
        # Prepara os segmentos para a próxima etapa
        segmentos_whisper = [
            {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
            for seg in transcricao.segments
        ]
        
        print("\n--- TRANSCRIÇÃO BRUTA RECEBIDA ---")
        for seg in segmentos_whisper:
            print(f"[{seg['start']:05.2f} - {seg['end']:05.2f}] {seg['text']}")

        # 3. Análise Semântica com IA para identificar trechos úteis
        segmentos_uteis = process.refinar_transcricao_com_ia(segmentos_whisper)
        
        print("\n--- SEGMENTOS ÚTEIS (IA) ---")
        print(segmentos_uteis)

    except Exception as e:
        print(f"Ocorreu um erro inesperado ao processar {filepath}: {e}")
    finally:
        # 9. Limpeza de arquivos temporários
        if os.path.exists(caminho_audio_temp):
            os.remove(caminho_audio_temp)
            print(f"Arquivo temporário '{caminho_audio_temp}' removido.")


def start_watchdog(path="input_videos"):
    event_handler = VideoHandler()
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
    start_watchdog()