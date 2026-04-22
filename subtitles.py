import os
from utils import run_ffmpeg_command

def _gerar_cabecalho_ass() -> str:
    """Gera o cabeçalho padrão para um arquivo de legenda .ass com o estilo 'ReelsStyle'."""
    return """[Script Info]
Title: Legendas Geradas Automaticamente
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ReelsStyle,Arial,75,&H00FFFF,&H00000000,&H000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

def _format_ass_time(seconds: float) -> str:
    """Converte segundos para o formato de tempo ASS (H:MM:SS.cs)."""
    centis = int((seconds - int(seconds)) * 100)
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:01}:{minutes:02}:{seconds:02}.{centis:02}"

def _agrupar_palavras_em_blocos(
    lista_palavras: list[dict], 
    max_palavras_por_bloco: int = 4, 
    max_gap_segundos: float = 0.4,
    max_duracao_bloco: float = 2.5
) -> list[dict]:
    """
    Agrupa palavras com timestamps em blocos de legenda de forma inteligente,
    respeitando limites de palavras, pausas e duração total.
    
    Args:
        lista_palavras (list[dict]): Lista de palavras com 'word', 'start', 'end'.
        max_palavras_por_bloco (int): Número máximo de palavras por legenda.
        max_gap_segundos (float): A pausa máxima permitida entre palavras antes de forçar um novo bloco.
        max_duracao_bloco (float): A duração máxima em segundos para um único bloco de legenda.
    
    Returns:
        list[dict]: Uma lista de blocos de legenda com 'text', 'start', 'end'.
    """
    if not lista_palavras:
        return []

    blocos_de_legenda = []
    bloco_atual = []

    def finalizar_bloco(bloco_a_finalizar):
        if not bloco_a_finalizar:
            return
        texto = " ".join([p['word'] for p in bloco_a_finalizar])
        start = bloco_a_finalizar[0]['start']
        end = bloco_a_finalizar[-1]['end']
        blocos_de_legenda.append({"text": texto, "start": start, "end": end})

    for palavra in lista_palavras:
        if not bloco_atual:
            bloco_atual.append(palavra)
            continue

        # Regra 1: Limite de palavras
        if len(bloco_atual) >= max_palavras_por_bloco:
            finalizar_bloco(bloco_atual)
            bloco_atual = [palavra]
            continue

        # Regra 2: Gap temporal (pausa entre palavras)
        gap = palavra['start'] - bloco_atual[-1]['end']
        if gap > max_gap_segundos:
            finalizar_bloco(bloco_atual)
            bloco_atual = [palavra]
            continue

        # Regra 3: Duração máxima do bloco
        duracao_projetada = palavra['end'] - bloco_atual[0]['start']
        if duracao_projetada > max_duracao_bloco:
            finalizar_bloco(bloco_atual)
            bloco_atual = [palavra]
            continue

        # Se todas as regras passaram, adiciona a palavra ao bloco atual
        bloco_atual.append(palavra)

    # Finaliza o último bloco que pode ter sobrado
    finalizar_bloco(bloco_atual)

    return blocos_de_legenda

def gerar_ass(lista_palavras_transcritas: list[dict], segmentos_finais: list[dict], caminho_ass: str):
    """
    Gera um arquivo de legendas .ASS a partir da transcrição original,
    ajustando os timestamps para corresponder ao vídeo final concatenado.

    Args:
        lista_palavras_transcritas (list[dict]): Lista de palavras da transcrição do Whisper.
        segmentos_finais (list[dict]): Segmentos que foram mantidos no vídeo final.
        caminho_ass (str): Caminho para salvar o arquivo .ass gerado.
    """
    print("[ASS] Gerando arquivo de legendas...")
    
    ass_content = [_gerar_cabecalho_ass()]
    
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

    # 2. Agrupar palavras em blocos de legenda com tempos precisos
    blocos_de_legenda = _agrupar_palavras_em_blocos(lista_palavras_transcritas)

    # 3. Iterar sobre os blocos de legenda e ajustar os tempos para o vídeo final
    final_timeline_idx = 0 # Ponteiro para otimizar a busca em final_video_timeline

    try:
        for bloco in blocos_de_legenda:
            # Avança o ponteiro final_timeline_idx para o primeiro segmento final que pode se sobrepor
            temp_idx = final_timeline_idx # Inicia a busca a partir do último ponto
            while temp_idx < len(final_video_timeline) and final_video_timeline[temp_idx]['original_end'] <= bloco['start']:
                temp_idx += 1
            final_timeline_idx = temp_idx

            # Verifica sobreposições com os segmentos finais a partir do ponteiro atual
            for i in range(final_timeline_idx, len(final_video_timeline)):
                current_final_map = final_video_timeline[i]
                
                original_start_final = current_final_map['original_start']
                original_end_final = current_final_map['original_end']
                new_start_final = current_final_map['new_start']

                # Calcula a sobreposição entre o segmento de transcrição e o segmento final atual
                overlap_start = max(bloco['start'], original_start_final)
                overlap_end = min(bloco['end'], original_end_final)

                if overlap_start < overlap_end: # Há uma sobreposição
                    # Calcula o deslocamento de tempo para este segmento final
                    offset = new_start_final - original_start_final

                    # Aplica o deslocamento aos tempos do bloco
                    new_start_bloco = bloco['start'] + offset
                    new_end_bloco = bloco['end'] + offset

                    start_time_str = _format_ass_time(new_start_bloco)
                    end_time_str = _format_ass_time(new_end_bloco)
                    ass_line = f"Dialogue: 0,{start_time_str},{end_time_str},ReelsStyle,,0,0,0,,{bloco['text']}"
                    ass_content.append(ass_line)

                    if bloco['end'] <= original_end_final:
                        break
                elif original_start_final >= bloco['end']:
                    # Se o segmento final atual já começa depois que o bloco de legenda termina,
                    # não haverá mais sobreposições com segmentos finais posteriores (pois estão ordenados).
                    break

    except Exception as e:
        print(f"[ERRO NO ASS] Falha ao processar segmento de transcrição.")
        print(f"   - Erro: {e}")
        print(f"   - Bloco problemático: {bloco}")

    with open(caminho_ass, 'w', encoding='utf-8') as f:
        f.write("\n".join(ass_content))
    
    print(f"[ASS] Arquivo de legendas salvo em: {caminho_ass}")

def embutir_legendas(caminho_video_temp: str, caminho_ass: str, caminho_video_final: str, ffmpeg_path: str):
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
    caminho_ass_escapado = caminho_ass.replace('\\', '/').replace(':', '\\:')

    cmd = [
        ffmpeg_path,
        '-i', caminho_video_temp,
        '-vf', f"subtitles='{caminho_ass_escapado}'",
        '-c:a', 'copy', # Copia o áudio sem re-codificar
        '-y',
        caminho_video_final
    ]

    run_ffmpeg_command(cmd)
    print(f"[SUCESSO] Vídeo final com legendas embutidas salvo em: {caminho_video_final}")