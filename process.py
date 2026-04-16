import os
from openai import OpenAI
import json
import re
import subprocess

from utils import run_ffmpeg_command

def refinar_transcricao_com_ia(segmentos_transcricao: list[dict]) -> list[dict] | None:
    """
    Usa um modelo de IA via Groq para analisar os segmentos de transcrição e retornar
    apenas os timestamps do conteúdo útil em formato JSON.
    """
    try:
        # A chave de API é a mesma usada para a transcrição, conforme solicitado.
        api_key = os.getenv("GROQ_WHISPER_API")
        if not api_key:
            raise ValueError("A chave de API GROK_WHISPER_API não foi encontrada no arquivo .env")

        client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1"
        )

        print("\n[IA] Analisando transcrição com Qwen (via Groq) para identificar conteúdo útil...")

        # Formata a transcrição para ser enviada ao modelo
        transcricao_formatada = "\n".join(
            f"[{seg['start']:.2f} - {seg['end']:.2f}] {seg['text']}" for seg in segmentos_transcricao
        )

        # O prompt foi ajustado para instruir o modelo a retornar um JSON,
        # garantindo a compatibilidade com o resto do pipeline.
        mensagens = [
            {
                "role": "system",
                "content": """Você é um editor de vídeo. Analise a transcrição e retorne um JSON com os timestamps dos segmentos úteis.
REGRAS:
1. EXCLUA: Gaguejos, repetições, vícios de linguagem ('né', 'tipo', 'hum'), pausas e hesitações.
2. EXCLUA: Conversas sobre a gravação ('tá valendo', 'testando som', 'gravando'). Mantenha apenas o conteúdo principal do tema.
3. SEJA RIGOROSO: Priorize a concisão.
4. FORMATO: Sua resposta deve ser APENAS uma lista JSON de objetos com "start" e "end".
Exemplo: [{"start": 10.5, "end": 15.2}]"""
            },
            {
                "role": "user",
                "content": f"Analise esta transcrição e retorne o JSON com os trechos úteis:\n---\n{transcricao_formatada}\n---"
            }
        ]

        completion = client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=mensagens,
            temperature=0.2, # Temperatura baixa para respostas mais determinísticas e focadas no formato JSON
            max_tokens=4096,
            top_p=1,
            stream=False, # Stream desativado para receber a resposta JSON completa de uma vez
            response_format={"type": "json_object"}, # Força a saída em JSON
        )

        resposta_json_str = completion.choices[0].message.content
        print(f"[IA] Resposta JSON recebida: {resposta_json_str}")
        
        # Faz o parse da string JSON para um objeto Python
        segmentos_uteis = json.loads(resposta_json_str)
        return segmentos_uteis

    except Exception as e:
        print(f"Erro ao analisar transcrição com IA: {e}")
        return None

def detect_silences(video_path: str, ffmpeg_path: str, silence_thresh_db: int = -35, silence_duration: float = 1.0) -> list[dict]:
    """
    Detecta segmentos silenciosos em um vídeo usando o filtro silencedetect do FFmpeg.
    
    Args:
        video_path (str): Caminho para o arquivo de vídeo.
        ffmpeg_path (str): Caminho para o executável do FFmpeg.
        silence_thresh_db (int): O limite de ruído em dB. Níveis abaixo disso são considerados silêncio.
                                 O padrão é -60.
        silence_duration (float): A duração mínima em segundos que o silêncio deve ter para ser detectado.
                                  O padrão é 1.5.

    Returns:
        list[dict]: Uma lista de dicionários, cada um com chaves 'start' e 'end'
                    representando intervalos silenciosos em segundos.
    """
    print(f"\n[FFMPEG] Analisando áudio para cortes...")
    print(f"[FFMPEG] Parâmetros: Volume menor que {silence_thresh_db}dB por mais de {silence_duration}s")
    cmd = [
        ffmpeg_path,
        '-i', video_path,
        '-map', '0:a:0', # Seleciona apenas o primeiro stream de áudio
        '-af', f'silencedetect=n={silence_thresh_db}dB:d={silence_duration}',
        '-f', 'null',
        '-' # Saída para stdout (mas FFmpeg imprime logs para stderr)
    ]
    try:
        result = run_ffmpeg_command(cmd, capture_output=True, text=True)
        silences = []
        
        # Padrões Regex para encontrar silence_start e silence_end nos logs do FFmpeg
        start_pattern = re.compile(r'silence_start: (\d+\.?\d*)')
        end_pattern = re.compile(r'silence_end: (\d+\.?\d*)')

        current_silence_start = None

        # FFmpeg geralmente imprime logs para stderr
        for line in result.stderr.splitlines():
            start_match = start_pattern.search(line)
            end_match = end_pattern.search(line)

            if start_match:
                current_silence_start = float(start_match.group(1))
            elif end_match and current_silence_start is not None:
                silence_end = float(end_match.group(1))
                silences.append({"start": current_silence_start, "end": silence_end})
                current_silence_start = None # Reset para o próximo silêncio

        # LOG DE DEBUG ESSENCIAL: Mostra quantos silêncios reais o FFmpeg achou
        print(f"[FFMPEG] Resultado: {len(silences)} blocos de silêncio detectados!")
        if len(silences) == 0:
            print("[AVISO] Nenhum silêncio encontrado. O volume de corte (-35dB) pode estar muito baixo para o ruído deste vídeo, ou não há pausas longas.")
        return silences
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[ERRO] Falha ao detectar silêncios em '{video_path}': {e}")
        return []

def generate_non_silent_segments(duration: float, silences: list[dict]) -> list[dict]:
    """
    Gera segmentos não-silenciosos a partir de uma lista de segmentos silenciosos e duração total.
    Args:
        duration (float): Duração total do vídeo.
        silences (list[dict]): Lista de segmentos silenciosos, ex: [{"start": 1.0, "end": 2.0}].
    Returns:
        list[dict]: Lista de segmentos não-silenciosos.
    """
    non_silent_segments = []
    current_time = 0.0

    # Garante que os silêncios estão ordenados por tempo de início
    silences.sort(key=lambda x: x['start'])

    for silence in silences:
        silence_start = silence['start']
        silence_end = silence['end']

        # Se houver uma lacuna entre current_time e silence_start, é um segmento não-silencioso
        if silence_start > current_time:
            non_silent_segments.append({"start": current_time, "end": silence_start})
        
        # Avança current_time para depois do fim do silêncio
        current_time = max(current_time, silence_end)
    
    # Se houver tempo restante após o último silêncio, também é um segmento não-silencioso
    if current_time < duration:
        non_silent_segments.append({"start": current_time, "end": duration})
    
    print(f"Segmentos não-silenciosos gerados: {non_silent_segments}")
    return non_silent_segments


def merge_segments(segments1: list[dict], segments2: list[dict], tolerance: float = 1) -> list[dict]:
    """
    Encontra a interseção entre duas listas de segmentos de tempo e, em seguida,
    consolida quaisquer segmentos resultantes que estejam sobrepostos ou contíguos.

    Esta função é crucial para garantir que os intervalos de tempo enviados ao FFmpeg
    sejam precisos, não sobrepostos e representem a união de todos os trechos válidos.

    Args:
        segments1 (list[dict]): A primeira lista de segmentos (ex: úteis da IA).
                                Formato: [{"start": float, "end": float}].
        segments2 (list[dict]): A segunda lista de segmentos (ex: não-silenciosos do FFmpeg).
                                Formato: [{"start": float, "end": float}].
        tolerance (float): A lacuna máxima em segundos entre dois segmentos para que
                           eles sejam considerados contíguos e mesclados. Padrão 0.4s.

    Returns:
        list[dict]: Uma lista consolidada de segmentos representando a interseção
                    e a subsequente mesclagem de intervalos sobrepostos/contíguos.
                    Ex: [{"start": 1.0, "end": 2.8}] ou [{"start": 1.0, "end": 8.0}].
    """
    # 1. Garante que ambas as listas estão ordenadas pelo tempo de início
    segments1.sort(key=lambda x: x['start'])
    segments2.sort(key=lambda x: x['start'])

    intersections = []
    i, j = 0, 0

    # 2. Primeira passagem: Encontrar todas as interseções entre segments1 e segments2
    while i < len(segments1) and j < len(segments2):
        s1 = segments1[i]
        s2 = segments2[j]

        # Calcula o início e o fim da sobreposição (interseção)
        overlap_start = max(s1['start'], s2['start'])
        overlap_end = min(s1['end'], s2['end'])

        # Se houver uma sobreposição válida (início < fim), adiciona à lista de interseções
        if overlap_start < overlap_end:
            intersections.append({"start": overlap_start, "end": overlap_end})

        # Avança o ponteiro do segmento que termina primeiro para encontrar a próxima possível interseção
        if s1['end'] < s2['end']:
            i += 1
        else:
            j += 1
            
    # Se não houver interseções, retorna uma lista vazia
    if not intersections:
        print("Nenhuma interseção encontrada entre os segmentos.")
        return []

    # 3. Segunda passagem: Consolidar segmentos sobrepostos ou contíguos
    # As interseções já estão ordenadas por 'start' devido à lógica de dois ponteiros.
    consolidated_segments = [intersections[0]]

    for current_segment in intersections[1:]:
        last_merged_segment = consolidated_segments[-1]

        # Verifica se o segmento atual se sobrepõe ou é contíguo ao último segmento mesclado
        # A tolerância permite mesclar segmentos com pequenas lacunas entre eles (ex: [1, 2] e [2.1, 3] com tol=0.2 -> [1, 3])
        if current_segment['start'] <= last_merged_segment['end'] + tolerance:
            # Mescla os segmentos, estendendo o 'end' do último segmento mesclado
            last_merged_segment['end'] = max(last_merged_segment['end'], current_segment['end'])
        else:
            # Se não houver sobreposição/contiguidade, adiciona o segmento atual como um novo segmento mesclado
            consolidated_segments.append(current_segment)
            
    print(f"Segmentos mesclados e consolidados: {consolidated_segments}")
    return consolidated_segments
