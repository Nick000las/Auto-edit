import os
from openai import OpenAI
import json
import re
import subprocess
import string
from typing import List, Dict

from utils import run_ffmpeg_command

def refinar_transcricao_com_ia(texto_completo: str) -> str | None:
    """
    Usa um modelo de IA para "limpar" um texto de transcrição, removendo
    gaguejos, hesitações e erros de gravação.
    """
    try:
        # A chave de API é a mesma usada para a transcrição, pois estamos usando a API da Groq.
        api_key = os.getenv("GROQ_WHISPER_API")
        if not api_key:
            raise ValueError("A chave de API GROQ_WHISPER_API não foi encontrada no arquivo .env")

        client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1"
        )

        print("\n[IA] Enviando texto para limpeza (remoção de hesitações)...")

        mensagens = [
            {
                "role": "system",
                "content": """Você é um 'Revisor de Texto de Transcrição'. Sua única função é revisar o texto fornecido e DELETAR trechos que sejam claramente gaguejos, hesitações, palavras repetidas por engano ou erros de gravação.
                
REGRA NÚMERO UM (INQUEBRÁVEL): NÃO altere, reescreva, corrija a gramática ou adicione NENHUMA palavra. Apenas delete.

Exemplo:
Texto de entrada: "Eu, uhm... eu acho que... que a gente pode, pode começar."
Sua saída DEVE SER: "Eu acho que a gente pode começar."

Retorne APENAS o texto limpo como uma string contínua."""
            },
            {
                "role": "user",
                "content": texto_completo
            }
        ]

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=mensagens,
            temperature=0.2,
            max_tokens=4096,
            top_p=1,
            stream=False,
        )

        texto_limpo = completion.choices[0].message.content
        print(f"[IA] Texto limpo recebido: \"{texto_limpo[:100]}...\"")

        return texto_limpo

    except Exception as e:
        print(f"Erro ao analisar transcrição com IA: {e}")
        return None

def detect_silences(video_path: str, ffmpeg_path: str, silence_thresh_db: int = -35, silence_duration: float = 2.0) -> list[dict]:
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

    # Se não houver interseções, retorna uma lista vazia antes de tentar acessá-la
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

def filtrar_palavras_por_intervalos(palavras: List[Dict], intervalos_permitidos: List[Dict]) -> List[Dict]:
    """
    Filtra uma lista de palavras com timestamps, mantendo apenas aquelas que
    se sobrepõem com os intervalos de tempo permitidos.

    Args:
        palavras (List[Dict]): Lista de palavras, cada uma com 'start' e 'end'.
        intervalos_permitidos (List[Dict]): Lista de intervalos de tempo, cada um com 'start' e 'end'.

    Returns:
        List[Dict]: Uma nova lista contendo apenas as palavras filtradas.
    """
    palavras_filtradas = []
    intervalos_permitidos.sort(key=lambda x: x['start'])

    for palavra in palavras:
        for intervalo in intervalos_permitidos:
            # Verifica se há sobreposição entre a palavra e o intervalo
            if palavra['start'] < intervalo['end'] and palavra['end'] > intervalo['start']:
                palavras_filtradas.append(palavra)
                break # Palavra já foi incluída, passa para a próxima
    
    return palavras_filtradas

def alinhar_texto_com_palavras(texto_limpo: str, palavras_originais: List[Dict]) -> List[Dict]:
    """
    Alinha um texto limpo com a lista original de palavras para
    gerar os intervalos de tempo correspondentes ao texto mantido,
    ignorando pontuações perfeitamente.

    Args:
        texto_limpo (str): O texto limpo retornado pela IA.
        palavras_originais (List[Dict]): A lista original de palavras com 'word', 'start', 'end'.

    Returns:
        list[dict]: Uma lista de intervalos de tempo permitidos.
    """
    # 1. Remove toda e qualquer pontuação da IA antes de separar
    texto_sem_pontuacao_ia = texto_limpo.translate(str.maketrans('', '', string.punctuation))
    palavras_limpas = texto_sem_pontuacao_ia.lower().split()

    # 2. Remove toda e qualquer pontuação do Whisper
    palavras_originais_lower = []
    for p in palavras_originais:
        palavra_limpa = p['word'].translate(str.maketrans('', '', string.punctuation)).lower().strip()
        palavras_originais_lower.append((palavra_limpa, p))

    intervalos_permitidos = []
    idx_original = 0
    idx_original_atual = 0  # Ponteiro oficial que rastreia a posição cronológica

    for palavra_limpa in palavras_limpas:
        encontrado = False
        while idx_original < len(palavras_originais_lower):
            palavra_original_texto, palavra_original_obj = palavras_originais_lower[idx_original]
            idx_original += 1
            
            # Se as palavras limpas baterem, pega o tempo
        
        # Define a janela de busca para o ponteiro explorador
        limite_busca = min(idx_original_atual + 15, len(palavras_originais_lower))

        # O ponteiro explorador 'busca_idx' procura dentro da janela
        for busca_idx in range(idx_original_atual, limite_busca):
            palavra_original_texto, palavra_original_obj = palavras_originais_lower[busca_idx]

            # Se as palavras limpas baterem, o match é encontrado
            if palavra_original_texto == palavra_limpa:
                intervalos_permitidos.append({
                    "start": palavra_original_obj['start'],
                    "end": palavra_original_obj['end']
                })
                encontrado = True
                # Atualiza o ponteiro oficial para a posição logo após a palavra encontrada
                idx_original_atual = busca_idx + 1
                break
                

        # Se, após varrer a janela, a palavra não for encontrada, avisa e continua.
        # O ponteiro oficial não é alterado, permitindo a recuperação na próxima palavra.
        if not encontrado:
            print(f"[ALINHAMENTO] AVISO: A palavra '{palavra_limpa}' do texto da IA não foi encontrada na transcrição original.")

    return intervalos_permitidos
