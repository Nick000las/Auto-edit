import os
import google.generativeai as genai
from dotenv import load_dotenv
import json

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

def configurar_modelo_gemini():
    """Configura e retorna o modelo generativo do Gemini."""
    try:
        api_key = os.getenv("GEMINI_FLASH_API_KEY")
        if not api_key:
            raise ValueError("A chave de API GEMINI_FLASH_API_KEY não foi encontrada no arquivo .env")
        
        genai.configure(api_key=api_key)
        
        # Configurações para garantir uma resposta JSON mais consistente
        generation_config = {
            "temperature": 0.2,
            "response_mime_type": "application/json",
        }
        
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config=generation_config
        )
        return model
    except Exception as e:
        print(f"Erro ao configurar o modelo Gemini: {e}")
        return None

def refinar_transcricao_com_ia(segmentos_transcricao):
    """
    Usa o Gemini para analisar os segmentos de transcrição e retornar
    apenas os timestamps do conteúdo útil.
    """
    model = configurar_modelo_gemini()
    if not model:
        return None

    print("\n[IA] Analisando transcrição para identificar conteúdo útil...")

    # Formata a transcrição para ser enviada ao modelo
    transcricao_formatada = "\n".join(
        f"[{seg['start']:.2f} - {seg['end']:.2f}] {seg['text']}" for seg in segmentos_transcricao
    )

    prompt = f"""
    Você é um editor de vídeo experiente. Sua tarefa é analisar a transcrição de um vídeo, que inclui timestamps [inicio - fim] em segundos para cada segmento de fala.
    Identifique e selecione APENAS os segmentos que contêm conteúdo principal e útil. Ignore hesitações, vícios de linguagem (como "é...", "tipo...", "então..."), repetições desnecessárias e frases de preenchimento.

    Abaixo está a transcrição completa:
    ---
    {transcricao_formatada}
    ---

    Analise os segmentos e retorne uma lista JSON contendo objetos. Cada objeto deve ter as chaves "start" e "end", representando os timestamps exatos dos segmentos que DEVEM SER MANTIDOS no vídeo final.
    Não inclua segmentos inúteis. O formato de saída deve ser estritamente um JSON array.

    Exemplo de saída:
    [
      {{"start": 10.5, "end": 15.2}},
      {{"start": 18.0, "end": 25.5}}
    ]
    """

    resposta = model.generate_content(prompt)
    
    # O Gemini com response_mime_type="application/json" já retorna o texto parseado
    segmentos_uteis = json.loads(resposta.text)
    return segmentos_uteis
