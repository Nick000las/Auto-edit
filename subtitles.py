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

    A lógica corrige o problema de dessincronização ao pré-calcular o mapeamento
    da linha do tempo do vídeo final e, em seguida, aplicar os deslocamentos
    corretos para cada segmento de transcrição.

    Args:
        transcricao_original (list[dict]): Segmentos da transcrição do Whisper.
        segmentos_finais (list[dict]): Segmentos que foram mantidos no vídeo final.
        caminho_srt (str): Caminho para salvar o arquivo .srt gerado.
    """
    print("[SRT] Gerando arquivo de legendas...")
    srt_content = []
    index_legenda = 1

    # Garante que os segmentos finais estão ordenados por tempo de início
    segmentos_finais.sort(key=lambda x: x['start'])

    # 1. Pré-calcular o mapeamento da linha do tempo do vídeo final
    # final_video_timeline: [{"original_start": X, "original_end": Y, "new_start": A, "new_end": B}]
    final_video_timeline = []
    current_new_time = 0.0
    
    for seg_final in segmentos_finais:
        original_start_final = seg_final['start']
        original_end_final = seg_final['end']
        
        new_start_final = current_new_time
        new_end_final = current_new_time + (original_end_final - original_start_final)
        
        final_video_timeline.append({
            "original_start": original_start_final,
            "original_end": original_end_final,
            "new_start": new_start_final,
            "new_end": new_end_final
        })
        current_new_time = new_end_final

    # 2. Iterar sobre os segmentos de transcrição e ajustar os tempos
    final_timeline_idx = 0 # Ponteiro para otimizar a busca em final_video_timeline

    for seg_transcricao in transcricao_original:
        texto = seg_transcricao['text']
        trans_original_start = seg_transcricao['start']
        trans_original_end = seg_transcricao['end']

        # Avança o ponteiro final_timeline_idx para o primeiro segmento final que pode se sobrepor
        while final_timeline_idx < len(final_video_timeline) and \
              final_video_timeline[final_timeline_idx]['original_end'] <= trans_original_start:
            final_timeline_idx += 1

        # Verifica sobreposições com os segmentos finais a partir do ponteiro atual
        for i in range(final_timeline_idx, len(final_video_timeline)):
            current_final_map = final_video_timeline[i]
            
            original_start_final = current_final_map['original_start']
            original_end_final = current_final_map['original_end']
            new_start_final = current_final_map['new_start']

            # Calcula a sobreposição entre o segmento de transcrição e o segmento final atual
            overlap_start_original = max(trans_original_start, original_start_final)
            overlap_end_original = min(trans_original_end, original_end_final)

            if overlap_start_original < overlap_end_original: # Há uma sobreposição
                # Calcula o deslocamento de tempo para este segmento final
                offset = new_start_final - original_start_final
                
                new_overlap_start = overlap_start_original + offset
                new_overlap_end = overlap_end_original + offset

                # Adiciona o segmento ajustado ao conteúdo SRT
                srt_content.append(str(index_legenda))
                srt_content.append(f"{_format_srt_time(new_overlap_start)} --> {_format_srt_time(new_overlap_end)}")
                srt_content.append(texto)
                srt_content.append("")
                index_legenda += 1

                # Se o segmento de transcrição termina antes ou no final do segmento final atual,
                # não há mais sobreposições para este seg_transcricao com segmentos finais posteriores.
                if trans_original_end <= original_end_final:
                    break
            elif original_start_final >= trans_original_end:
                # Se o segmento final atual já começa depois que o segmento de transcrição termina,
                # não haverá mais sobreposições com segmentos finais posteriores (pois estão ordenados).
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