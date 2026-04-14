import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def transcrever_com_whisper(caminho_audio):

    print(f"Enviando '{caminho_audio}' para a OpenAI...")
    
    #arquivo não pode passar de 25MB na API da OpenAI.
    with open(caminho_audio, "rb") as arquivo_audio:
        
        resposta = client.audio.transcriptions.create(
            model="whisper-1",
            file=arquivo_audio,
            response_format="verbose_json",       # Necessário para receber tempos
            timestamp_granularities=["segment"]   # Divide o texto em blocos de fala
        )
        
    return resposta


if __name__ == "__main__":

    caminho_teste = "temp/audio_extraido.mp3" 
    
    try:
        # Verifica se o arquivo existe para não dar erro
        if not os.path.exists(caminho_teste):
            print(f"Crie um arquivo de áudio em '{caminho_teste}' para testar.")
        else:
            transcricao = transcrever_com_whisper(caminho_teste)
            
            print("\n--- RESULTADO COM TIMESTAMPS ---")
            
            # 4. Extração dos dados úteis para o próximo passo (Análise de IA)
            for segmento in transcricao.segments:
                inicio = segmento.start
                fim = segmento.end
                texto = segmento.text.strip()
                
                # É este formato que você enviará para o LLM analisar depois
                print(f"[{inicio:05.2f} - {fim:05.2f}] {texto}")
                
    except Exception as erro:
        print(f"Erro na API da OpenAI: {erro}")