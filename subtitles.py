import os
from utils import run_ffmpeg_command

def _format_srt_time(seconds: float) -> str:
    """Converte segundos para o formato de tempo SRT (HH:MM:SS,ms)."""
    millis = int((seconds - int(seconds)) * 1000)
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"

def gerar_srt(transcricao_original: list[dict], segmentos_finais: list[dict], caminho_srt: str):
    """
    Gera um arquivo de legendas .SRT a partir da transcrição original,
    ajustando os timestamps para corresponder ao vídeo final concatenado.

    Args:
        transcricao_original (list[dict]): Segmentos da transcrição do Whisper.
        segmentos_finais (list[dict]): Segmentos que foram mantidos no vídeo final.
        caminho_srt (str): Caminho para salvar o arquivo .srt gerado.
    """
    print("[SRT] Gerando arquivo de legendas...")
    duracao_removida_total = 0.0
    ultimo_fim_segmento_final = 0.0
    srt_content = []
    index_legenda = 1

    for seg_transcricao in transcricao_original:
        texto = seg_transcricao['text']
        inicio_original = seg_transcricao['start']
        fim_original = seg_transcricao['end']

        # Verifica se o segmento de transcrição está dentro de algum dos segmentos finais
        for seg_final in segmentos_finais:
            # Encontra a sobreposição entre o segmento de transcrição e o segmento final
            sobreposicao_inicio = max(inicio_original, seg_final['start'])
            sobreposicao_fim = min(fim_original, seg_final['end'])

            if sobreposicao_inicio < sobreposicao_fim:
                # Calcula a duração removida ANTES do início deste segmento final
                duracao_removida_antes = seg_final['start'] - ultimo_fim_segmento_final
                duracao_removida_total += duracao_removida_antes

                # Ajusta os tempos do segmento de transcrição
                novo_inicio = inicio_original - duracao_removida_total
                novo_fim = fim_original - duracao_removida_total

                # Adiciona ao conteúdo SRT
                srt_content.append(str(index_legenda))
                srt_content.append(f"{_format_srt_time(novo_inicio)} --> {_format_srt_time(novo_fim)}")
                srt_content.append(texto)
                srt_content.append("")

                index_legenda += 1
                ultimo_fim_segmento_final = seg_final['end']
                # Sai do loop interno, pois o segmento de transcrição já foi mapeado
                break

    with open(caminho_srt, 'w', encoding='utf-8') as f:
        f.write("\n".join(srt_content))
    
    print(f"[SRT] Arquivo de legendas salvo em: {caminho_srt}")

def embutir_legendas(caminho_video_temp: str, caminho_srt: str, caminho_video_final: str, ffmpeg_path: str):
    """
    Embute (hardcode) um arquivo de legendas .srt em um vídeo usando FFmpeg.

    Args:
        caminho_video_temp (str): Caminho para o vídeo de entrada (editado, sem legendas).
        caminho_srt (str): Caminho para o arquivo .srt.
        caminho_video_final (str): Caminho para salvar o vídeo final com legendas.
        ffmpeg_path (str): Caminho para o executável do FFmpeg.
    """
    print("[FFMPEG] Embutindo legendas no vídeo final...")
    
    # FFmpeg no Windows requer que as barras invertidas e os dois pontos sejam escapados no filtro
    caminho_srt_escapado = caminho_srt.replace('\\', '/').replace(':', '\\:')

    cmd = [
        ffmpeg_path,
        '-i', caminho_video_temp,
        '-vf', f"subtitles='{caminho_srt_escapado}'",
        '-c:a', 'copy', # Copia o áudio sem re-codificar
        '-y',
        caminho_video_final
    ]

    run_ffmpeg_command(cmd)
    print(f"[SUCESSO] Vídeo final com legendas embutidas salvo em: {caminho_video_final}")