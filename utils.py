import subprocess
import re
import os
import shutil
import time

def run_ffmpeg_command(cmd: list, capture_output=True, text=True):
    """
    Executa um comando FFmpeg/FFprobe.
    Args:
        cmd (list): O comando como uma lista de strings.
        capture_output (bool): Se deve capturar stdout e stderr.
        text (bool): Se deve decodificar stdout e stderr como texto.
    Returns:
        subprocess.CompletedProcess: O resultado da chamada do subprocesso.
    Raises:
        subprocess.CalledProcessError: Se o comando retornar um código de saída diferente de zero.
        FileNotFoundError: Se 'ffmpeg' ou 'ffprobe' não for encontrado.
    """
    try:
        result = subprocess.run(cmd, check=True, capture_output=capture_output, text=text)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Erro ao executar comando FFmpeg/FFprobe: {e.cmd}")
        print(f"STDOUT: {e.stdout}")
        print(f"STDERR: {e.stderr}")
        raise
    except FileNotFoundError:
        print(f"Erro: Executável '{cmd[0]}' não encontrado. Verifique se o FFmpeg está instalado e se o caminho está correto no seu arquivo .env (FFMPEG_PATH, FFPROBE_PATH) ou no PATH do sistema.")
        raise

def get_video_duration(video_path: str, ffprobe_path: str) -> float:
    """
    Obtém a duração de um arquivo de vídeo usando ffprobe.
    Args:
        video_path (str): Caminho para o arquivo de vídeo.
    Returns:
        float: A duração do vídeo em segundos.
    Raises:
        ValueError: Se a duração não puder ser determinada.
    """
    cmd = [
        ffprobe_path, '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', video_path
    ]
    result = run_ffmpeg_command(cmd)
    duration = float(result.stdout.strip())
    return duration

def aguardar_arquivo_estabilizar(filepath: str, check_interval: int = 2, timeout: int = 120) -> bool:
    """
    Aguarda até que o tamanho de um arquivo pare de mudar, indicando que a escrita terminou.

    Args:
        filepath (str): Caminho para o arquivo.
        check_interval (int): Intervalo em segundos entre as verificações.
        timeout (int): Tempo máximo em segundos para aguardar.

    Returns:
        bool: True se o arquivo estabilizou, False se o tempo limite foi atingido.
    """
    start_time = time.time()
    last_size = -1

    print(f"[ESTABILIZANDO] Monitorando '{os.path.basename(filepath)}' para estabilização...")
    while time.time() - start_time < timeout:
        try:
            if not os.path.exists(filepath):
                time.sleep(check_interval)
                continue

            current_size = os.path.getsize(filepath)
            if current_size > 0 and current_size == last_size:
                print(f"[ESTABILIZANDO] Arquivo '{os.path.basename(filepath)}' estável com {current_size} bytes.")
                return True
            
            last_size = current_size
            time.sleep(check_interval)
        except FileNotFoundError:
            time.sleep(check_interval)
            continue

    print(f"[ESTABILIZANDO] ERRO: Tempo limite de {timeout}s atingido ao aguardar a estabilização de '{filepath}'.")
    return False

def check_ffmpeg_paths(ffmpeg_path: str, ffprobe_path: str):
    """
    Verifica se os executáveis do FFmpeg e FFprobe são encontrados.
    Levanta FileNotFoundError com uma mensagem detalhada se não forem encontrados.
    """
    if not shutil.which(ffmpeg_path):
        raise FileNotFoundError(
            f"Executável FFmpeg não encontrado em '{ffmpeg_path}'.\n"
            "Por favor, verifique se o FFmpeg está instalado e se a variável FFMPEG_PATH no seu arquivo .env aponta para o caminho correto do executável.\n"
            'Exemplo para .env: FFMPEG_PATH="D:/ffmpeg/bin/ffmpeg.exe"'
        )
    if not shutil.which(ffprobe_path):
        raise FileNotFoundError(
            f"Executável FFprobe não encontrado em '{ffprobe_path}'.\n"
            "Por favor, verifique se o FFmpeg está instalado e se a variável FFPROBE_PATH no seu arquivo .env aponta para o caminho correto do executável.\n"
            'Exemplo para .env: FFPROBE_PATH="D:/ffmpeg/bin/ffprobe.exe"'
        )
    
    print("[CONFIGURAÇÃO OK] FFmpeg e FFprobe encontrados.")
