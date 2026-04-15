import os
import subprocess
from utils import run_ffmpeg_command

def cortar_e_concatenar(caminho_video_original: str, segmentos_finais: list[dict], caminho_saida: str, ffmpeg_path: str):
    """
    Corta um vídeo em múltiplos segmentos e os concatena em um único arquivo de saída.

    Esta função usa FFmpeg para:
    1. Cortar o vídeo original nos intervalos de tempo especificados em 'segmentos_finais'.
       Os cortes são feitos com '-c copy' para evitar re-codificação e manter a qualidade.
    2. Gerar um arquivo de texto listando todos os clipes temporários.
    3. Usar o demuxer 'concat' do FFmpeg para juntar os clipes em um único vídeo final.
    4. Limpar os arquivos temporários (clipes e lista de concatenação).

    Args:
        caminho_video_original (str): Caminho para o vídeo de entrada.
        segmentos_finais (list[dict]): Lista de dicionários com 'start' e 'end' para os cortes.
        caminho_saida (str): Caminho para o arquivo de vídeo final editado.
        ffmpeg_path (str): Caminho para o executável do FFmpeg.

    Returns:
        bool: True se a operação for bem-sucedida, False caso contrário.
    """
    if not segmentos_finais:
        print("[EDITOR] Nenhum segmento para cortar. Operação abortada.")
        return False

    temp_clip_dir = os.path.join("temp", "clips")
    os.makedirs(temp_clip_dir, exist_ok=True)

    lista_clipes_temp = []
    caminho_arquivo_lista = os.path.join(temp_clip_dir, "concat_list.txt")

    try:
        # Etapa 1: Cortar o vídeo em clipes temporários
        print(f"[EDITOR] Cortando {len(segmentos_finais)} segmentos do vídeo original...")
        for i, segmento in enumerate(segmentos_finais):
            start_time = segmento['start']
            end_time = segmento['end']
            caminho_clip_temp = os.path.join(temp_clip_dir, f"clip_{i}.mp4")
            lista_clipes_temp.append(caminho_clip_temp)

            cmd_corte = [
                ffmpeg_path,
                # -ss e -to antes de -i para um corte mais rápido, mas pode ser impreciso.
                # Para cortes precisos, coloque-os depois de -i.
                '-i', caminho_video_original,
                '-ss', str(start_time),
                '-to', str(end_time),
                '-c:v', 'libx264', # Re-codifica o vídeo para permitir cortes precisos
                '-threads', '2', # Limita o uso de threads para evitar sobrecarga da CPU
                '-preset', 'ultrafast', # Prioriza a velocidade de codificação
                '-c:a', 'aac',          # Re-codifica o áudio para o formato AAC
                '-y',
                caminho_clip_temp
            ]
            run_ffmpeg_command(cmd_corte)

        # Etapa 2: Criar arquivo de texto para concatenação
        with open(caminho_arquivo_lista, 'w') as f:
            for clip_path in lista_clipes_temp:
                # FFmpeg requer que as barras invertidas sejam escapadas ou substituídas
                f.write(f"file '{os.path.basename(clip_path)}'\n")

        # Etapa 3: Concatenar os clipes
        print("[EDITOR] Concatenando clipes para criar o vídeo final...")
        cmd_concat = [
            ffmpeg_path,
            '-f', 'concat',
            '-safe', '0',  # Necessário para permitir caminhos relativos no arquivo de lista
            '-i', caminho_arquivo_lista,
            '-c', 'copy',
            '-y',
            caminho_saida
        ]
        run_ffmpeg_command(cmd_concat)
        print(f"[SUCESSO] Vídeo final salvo em: {caminho_saida}")
        return True

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[ERRO NO EDITOR] Falha ao cortar ou concatenar o vídeo: {e}")
        return False

    finally:
        # Etapa 4: Limpeza dos arquivos temporários
        if os.path.exists(caminho_arquivo_lista):
            os.remove(caminho_arquivo_lista)
        for clip_path in lista_clipes_temp:
            if os.path.exists(clip_path):
                os.remove(clip_path)
        print("[EDITOR] Arquivos temporários limpos.")