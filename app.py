import os
import struct
import io
from flask import Flask, request, jsonify, send_file, make_response # Adicionado make_response
from flask_cors import CORS
from google import genai
from google.genai import types

app = Flask(__name__)
# Configuração de CORS para aceitar qualquer origem e expor o cabeçalho
CORS(app, origins="*", expose_headers=['X-Model-Used'])

def convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    parameters = parse_audio_mime_type(mime_type)
    bits_per_sample = parameters.get("bits_per_sample", 16)
    sample_rate = parameters.get("rate", 24000)
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", chunk_size, b"WAVE", b"fmt ", 16, 1,
        num_channels, sample_rate, byte_rate, block_align,
        bits_per_sample, b"data", data_size
    )
    return header + audio_data

def parse_audio_mime_type(mime_type: str) -> dict[str, int]:
    bits_per_sample = 16
    rate = 24000
    parts = mime_type.split(";")
    for param in parts:
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate_str = param.split("=", 1)[1]
                rate = int(rate_str)
            except (ValueError, IndexError): pass
        elif param.startswith("audio/L"):
            try:
                bits_per_sample = int(param.split("L", 1)[1])
            except (ValueError, IndexError): pass
    return {"bits_per_sample": bits_per_sample, "rate": rate}

@app.route('/')
def home():
    return "Backend do Gerador de Narração está online."

@app.route('/api/generate-audio', methods=['POST'])
def generate_audio_endpoint():
    # Nota: A URL no main.js precisa ser '/api/generate-audio'
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Configuração do servidor incompleta: Chave da API ausente."}), 500

    data = request.get_json()
    if not data:
        return jsonify({"error": "Requisição inválida, corpo JSON ausente."}), 400
        
    text_to_narrate = data.get('text')
    voice_name = data.get('voice')
    style_instructions_text = data.get('style')

    if not text_to_narrate:
        return jsonify({"error": "O texto não pode estar vazio."}), 400

    try:
        client = genai.Client(api_key=api_key)
        
        # Vamos usar APENAS o modelo Pro por enquanto para simplificar
        model = "gemini-2.5-pro-preview-tts"
        model_to_use = "Pro" # Definimos qual modelo foi usado

        parts_list = []
        if style_instructions_text:
            parts_list.append(types.Part.from_text(text=style_instructions_text))
        parts_list.append(types.Part.from_text(text=text_to_narrate))
        
        contents = [types.Content(role="user", parts=parts_list)]
        
        generate_content_config = types.GenerateContentConfig(
            response_modalities=["audio"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
        )
        
        audio_buffer = bytearray()
        audio_mime_type = "audio/L16;rate=24000"
        
        stream = client.models.generate_content_stream(model=model, contents=contents, config=generate_content_config)
        
        for chunk in stream:
            if (chunk.candidates and chunk.candidates[0].content and
                chunk.candidates[0].content.parts and chunk.candidates[0].content.parts[0].inline_data and
                chunk.candidates[0].content.parts[0].inline_data.data):
                inline_data = chunk.candidates[0].content.parts[0].inline_data
                audio_buffer.extend(inline_data.data)
                audio_mime_type = inline_data.mime_type

        if not audio_buffer:
            return jsonify({"error": "Não foi possível gerar o áudio."}), 500

        wav_data = convert_to_wav(bytes(audio_buffer), audio_mime_type)
        
        # Cria a resposta e adiciona o cabeçalho
        response = make_response(send_file(io.BytesIO(wav_data), mimetype='audio/wav', as_attachment=False))
        response.headers['X-Model-Used'] = model_to_use
        return response

    except Exception as e:
        print(f"Ocorreu um erro na API: {e}")
        return jsonify({"error": f"Erro ao contatar a API do Gemini: {e}"}), 500