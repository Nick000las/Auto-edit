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

def quebrar_texto(texto: str, inicio: float, fim: float, max_palavras: int = 4) -> list[dict]:
    """
    Divide um texto em pedaços menores e calcula o tempo proporcional para cada um.

    Args:
        texto (str): O texto completo do segmento.
        inicio (float): O tempo de início original do segmento.
        fim (float): O tempo de fim original do segmento.
        max_palavras (int): O número máximo de palavras por pedaço de legenda.

    Returns:
        list[dict]: Uma lista de dicionários, cada um representando um pedaço
                    de legenda com 'text', 'start' e 'end'.
    """
    palavras = texto.split()
    if not palavras:
        return []

    duracao_total = fim - inicio
    tempo_por_palavra = duracao_total / len(palavras)
    
    pedacos = []
    tempo_atual = inicio
    for i in range(0, len(palavras), max_palavras):
        chunk_palavras = palavras[i:i + max_palavras]
        chunk_texto = " ".join(chunk_palavras)
        chunk_duracao = len(chunk_palavras) * tempo_por_palavra
        pedacos.append({"text": chunk_texto, "start": tempo_atual, "end": tempo_atual + chunk_duracao})
        tempo_atual += chunk_duracao
    return pedacos

def gerar_ass(transcricao_original: list[dict], segmentos_finais: list[dict], caminho_ass: str):
    """
    Gera um arquivo de legendas .ASS a partir da transcrição original,
    ajustando os timestamps para corresponder ao vídeo final concatenado.

    A lógica corrige o problema de dessincronização ao pré-calcular o mapeamento
    da linha do tempo e aplicar os deslocamentos corretos para cada segmento de
    transcrição. A função agora é robusta para aceitar tanto objetos quanto dicionários.

    Args:
        transcricao_original (list[dict] or list[object]): Segmentos da transcrição do Whisper.
        segmentos_finais (list[dict]): Segmentos que foram mantidos no vídeo final.
        caminho_ass (str): Caminho para salvar o arquivo .ass gerado.
    """
    print("[ASS] Gerando arquivo de legendas...")
    
    ass_content = [_gerar_cabecalho_ass()]
    
    # Log de debug para verificar o tipo de dado recebido
    if transcricao_original:
        print(f'[DEBUG] Tipo recebido no ASS: {type(transcricao_original[0])}')

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

    try:
        for seg_transcricao in transcricao_original:
            # Lógica para extrair dados, seja de um objeto ou de um dicionário
            texto = seg_transcricao.text if hasattr(seg_transcricao, 'text') else seg_transcricao['text']
            trans_original_start = seg_transcricao.start if hasattr(seg_transcricao, 'start') else seg_transcricao['start']
            trans_original_end = seg_transcricao.end if hasattr(seg_transcricao, 'end') else seg_transcricao['end']

            # Avança o ponteiro final_timeline_idx para o primeiro segmento final que pode se sobrepor
            temp_idx = final_timeline_idx
            while temp_idx < len(final_video_timeline) and \
                  final_video_timeline[temp_idx]['original_end'] <= trans_original_start:
                temp_idx += 1
            final_timeline_idx = temp_idx

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

                    # Quebra o texto original em pedaços menores com tempos proporcionais
                    pedacos_de_legenda = quebrar_texto(texto, trans_original_start, trans_original_end)

                    for pedaco in pedacos_de_legenda:
                        # Verifica se o pedaço atual está dentro da sobreposição do vídeo final
                        if pedaco['start'] < overlap_end_original and pedaco['end'] > overlap_start_original:
                            # Aplica o deslocamento aos tempos do pedaço
                            new_start_pedaco = pedaco['start'] + offset
                            new_end_pedaco = pedaco['end'] + offset

                            # Adiciona o pedaço ajustado como uma linha de diálogo separada
                            start_time_str = _format_ass_time(new_start_pedaco)
                            end_time_str = _format_ass_time(new_end_pedaco)
                            ass_line = f"Dialogue: 0,{start_time_str},{end_time_str},ReelsStyle,,0,0,0,,{pedaco['text']}"
                            ass_content.append(ass_line)

                    # Se o segmento de transcrição termina antes ou no final do segmento final atual,
                    # não há mais sobreposições para este seg_transcricao com segmentos finais posteriores.
                    if trans_original_end <= original_end_final:
                        break
                elif original_start_final >= trans_original_end:
                    # Se o segmento final atual já começa depois que o segmento de transcrição termina,
                    # não haverá mais sobreposições com segmentos finais posteriores (pois estão ordenados).
                    break

    except Exception as e:
        print(f"[ERRO NO ASS] Falha ao processar segmento de transcrição.")
        print(f"   - Erro: {e}")
        print(f"   - Segmento problemático: {seg_transcricao}")

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