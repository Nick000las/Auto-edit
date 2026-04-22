import os
from openai import OpenAI

def inicializar_cliente_groq():
    """
    Inicializa e retorna o cliente para a API da Groq, verificando a chave de API.
    Levanta um ValueError se a chave não for encontrada.
    """
    # Altera a variável de ambiente para a chave da Groq
    api_key = os.getenv("GROQ_WHISPER_API")
    if not api_key:
        raise ValueError("A chave de API GROK_WHISPER_API não foi encontrada. Verifique seu arquivo .env.")
    # Adiciona a base_url para apontar para a API da Groq
    return OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1"
    )

client = inicializar_cliente_groq()

def transcrever_com_whisper(caminho_audio):
    print(f"Enviando '{caminho_audio}' para a Groq API...")
    
    try:
        with open(caminho_audio, "rb") as arquivo_audio:
            resposta = client.audio.transcriptions.create(
                # Altera o modelo para o que é usado pela Groq
                model="whisper-large-v3",
                file=arquivo_audio,
                response_format="verbose_json",       # Necessário para receber tempos
                language='pt',                        # Força o modelo a usar a rede neural em português
                timestamp_granularities=["word"],     # Divide o texto em palavras com timestamps
                temperature=0.0,                      # Força o modelo a ser determinístico
                prompt="Este é um vídeo em português do Brasil. Transcreva as palavras completas, sem abreviações. Exemplo: não, preço, caráter, inteligência." # Contexto para ancorar o modelo
            )
            

        return resposta
    except Exception as e:
        print(f"[ERRO NA TRANSCRIÇÃO] A chamada para a API da Groq falhou: {e}")
        return None


if __name__ == "__main__":

    caminho_teste = "temp/IMG_2252.mp3" 
    
    try:
        # Verifica se o arquivo existe para não dar erro
        if not os.path.exists(caminho_teste):
            print(f"Crie um arquivo de áudio em '{caminho_teste}' para testar.")
        else:
            transcricao = transcrever_com_whisper(caminho_teste)
            
            print("\n--- RESULTADO COM TIMESTAMPS ---")
            
            # Extração dos dados por palavra para verificação
            if hasattr(transcricao, 'words'):
                for palavra in transcricao.words:
                    inicio = palavra.start
                    fim = palavra.end
                    texto = palavra.word
                    print(f"[{inicio:05.2f} - {fim:05.2f}] {texto}")
            else:
                print("A resposta da API não continha timestamps por palavra. Verifique a resposta completa:")
                print(transcricao)
                
    except Exception as erro:
        print(f"Erro na API da Groq: {erro}")