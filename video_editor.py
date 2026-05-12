import os
import subprocess
from utils import run_ffmpeg_command

def editar_e_legendar_em_passo_unico(
    caminho_video_original: str,
    segmentos_finais: list[dict],
    caminho_ass: str,
    caminho_saida: str,
    ffmpeg_path: str
) -> bool:
    """
    Edita um vídeo (cortando segmentos) e embute legendas em uma única passagem do FFmpeg.

    Esta função usa o `filter_complex` do FFmpeg para:
    1. Selecionar os segmentos de vídeo e áudio desejados com base em 'segmentos_finais'.
    2. Resetar os timestamps (PTS/ATPS) para criar um clipe contínuo.
    3. Embutir o arquivo de legenda .ass no stream de vídeo resultante.
    4. Codificar o resultado final em um único comando, evitando arquivos intermediários e múltiplas re-codificações.

    Args:
        caminho_video_original (str): Caminho para o vídeo de entrada.
        segmentos_finais (list[dict]): Lista de dicionários com 'start' e 'end' para os cortes.
        caminho_ass (str): Caminho para o arquivo .ass a ser embutido.
        caminho_saida (str): Caminho para o arquivo de vídeo final.
        ffmpeg_path (str): Caminho para o executável do FFmpeg.

    Returns:
        bool: True se a operação for bem-sucedida, False caso contrário.
    """
    if not segmentos_finais:
        print("[EDITOR] Nenhum segmento para editar. Operação abortada.")
        return False

    try:
        # 1. Construir a string para os filtros 'select' e 'aselect'
        select_filter_parts = [f"between(t,{seg['start']},{seg['end']})" for seg in segmentos_finais]
        select_str = "+".join(select_filter_parts)

        # 2. Escapar o caminho do arquivo .ass para o filtro de legendas
        caminho_ass_escapado = caminho_ass.replace('\\', '/').replace(':', '\\:')

        # 3. Montar a string completa do filter_complex
        filter_complex = (
            f"[0:v]select='{select_str}',setpts=N/FRAME_RATE/TB[v];"
            f"[0:a]aselect='{select_str}',asetpts=N/SR/TB[a];"
            f"[v]subtitles='{caminho_ass_escapado}'[outv]"
        )

        print("[EDITOR] Iniciando edição e legendagem em passo único...")

        # 4. Montar o comando final do FFmpeg
        cmd = [
            ffmpeg_path,
            '-i', caminho_video_original,
            '-filter_complex', filter_complex,
            '-map', '[outv]',
            '-map', '[a]',
            '-y',
            caminho_saida
        ]

        run_ffmpeg_command(cmd)
        print(f"[SUCESSO] Vídeo final editado e legendado salvo em: {caminho_saida}")
        return True

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[ERRO NO EDITOR] Falha ao processar o vídeo em passo único: {e}")
        return False
