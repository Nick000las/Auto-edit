import os
from openai import OpenAI
import json
import re

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
                "content": """Você é um editor de vídeo experiente. Sua tarefa é analisar a transcrição de um vídeo, que inclui timestamps [inicio - fim] em segundos.
Identifique e selecione APENAS os segmentos que contêm conteúdo principal e útil. Ignore hesitações, vícios de linguagem, repetições e frases de preenchimento.
Sua resposta deve ser APENAS uma lista JSON de objetos. Cada objeto deve ter as chaves "start" e "end", representando os timestamps exatos dos segmentos que DEVEM SER MANTIDOS.
Exemplo de saída: [{"start": 10.5, "end": 15.2}, {"start": 18.0, "end": 25.5}]"""
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

def detect_silences(video_path: str, ffmpeg_path: str) -> list[dict]:
    """
    Detecta segmentos silenciosos em um vídeo usando o filtro silencedetect do FFmpeg.
    Args:
        video_path (str): Caminho para o arquivo de vídeo.
    Returns:
        list[dict]: Uma lista de dicionários, cada um com chaves 'start' e 'end'
                    representando intervalos silenciosos em segundos.
    """
    print(f"[FFMPEG] Detectando silêncios em '{video_path}'...")
    # Usa -vn para processar apenas áudio, -af para filtro de áudio
    # silencedetect=n=-50dB:d=1s -> threshold de ruído -50dB, duração mínima de 1 segundo
    cmd = [
        ffmpeg_path,
        '-i', video_path,
        '-map', '0:a:0', # Seleciona apenas o primeiro stream de áudio
        '-af', 'silencedetect=n=-50dB:d=1', # Ajuste o ruído (n) e a duração (d) conforme necessário
        '-f', 'null',
        '-' # Saída para stdout (mas FFmpeg imprime logs para stderr)
    ]
    try:
        result = run_ffmpeg_command(cmd, capture_output=True, text=True)
        silences = []
        
        # Padrões Regex para encontrar silence_start e silence_end
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
        
        print(f"Silêncios detectados: {silences}")
        return silences
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"Falha ao detectar silêncios em '{video_path}'. Retornando lista vazia.")
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

def merge_segments(segments1: list[dict], segments2: list[dict]) -> list[dict]:
    """
    Encontra a interseção entre duas listas de segmentos de tempo.

    Esta função recebe duas listas de segmentos (ex: segmentos úteis da IA e
    segmentos não-silenciosos do FFmpeg) e retorna uma nova lista contendo
    apenas os intervalos de tempo que existem em *ambas* as listas.

    Args:
        segments1 (list[dict]): A primeira lista de segmentos. Ex: [{"start": 0.5, "end": 2.8}]
        segments2 (list[dict]): A segunda lista de segmentos. Ex: [{"start": 1.0, "end": 3.0}]

    Returns:
        list[dict]: Uma lista de segmentos representando a interseção.
                    Ex: [{"start": 1.0, "end": 2.8}]
    """
    merged = []
    i, j = 0, 0

    # Garante que ambas as listas estão ordenadas pelo tempo de início
    segments1.sort(key=lambda x: x['start'])
    segments2.sort(key=lambda x: x['start'])

    while i < len(segments1) and j < len(segments2):
        s1 = segments1[i]
        s2 = segments2[j]

        # Calcula a sobreposição (interseção) entre os dois segmentos atuais
        overlap_start = max(s1['start'], s2['start'])
        overlap_end = min(s1['end'], s2['end'])

        # Se houver uma sobreposição válida (início < fim), adiciona à lista
        if overlap_start < overlap_end:
            merged.append({"start": overlap_start, "end": overlap_end})

        # Avança o ponteiro do segmento que termina primeiro
        if s1['end'] < s2['end']:
            i += 1
        else:
            j += 1
            
    print(f"Segmentos mesclados (interseção): {merged}")
    return merged
