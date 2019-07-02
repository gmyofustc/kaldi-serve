import traceback

from io import BytesIO
from pprint import pprint

from pydub import AudioSegment
from pydub.silence import detect_nonsilent

from kaldi import (
    KaldiClient,
    RecognitionAudio,
    RecognitionConfig
)

def get_chunks(filename, chunk_len=1):
    audio = AudioSegment.from_file(filename, format='wav', frame_rate=8000, channels=1, sample_width=2)

    print(f'sample_width: {audio.sample_width}')
    print(f'audio len: {len(audio)}')
    print(f'channels: {audio.channels}')
    print(f'frame rate: {audio.frame_rate}')

    if audio.duration_seconds == chunk_len:
        audio_stream = BytesIO()
        audio.export(audio_stream, format='wav')
        return [audio_stream.getvalue()]

    chunks = []
    for i in range(0, len(audio), int(chunk_len * 1000)):
        chunk = audio[i: i + chunk_len * 1000]
        chunk_stream = BytesIO()
        chunk.export(chunk_stream, format='wav')
        chunks.append(chunk_stream.getvalue())

    return chunks

client = None

def transcribe_file(audio_chunks, language_code='hi', **kwargs):
    """Transcribe the given audio file."""
    print(f'no. of audio chunks: {len(audio_chunks)}')
    global client
    if not client:
        client = KaldiClient()
    response = {}

    status_code = 200
    encoding = RecognitionConfig.AudioEncoding.LINEAR16
     
    audio = [RecognitionAudio(content=chunk) for chunk in audio_chunks]
    config = RecognitionConfig(
        sample_rate_hertz=kwargs.get('sampling_rate', 8000),
        encoding = encoding,
        language_code=language_code,
        max_alternatives=10,
        model=kwargs.get('model', None),
    )

    try:
        response = client.recognize(config, audio, uuid=kwargs.get('uuid', ''), timeout=3)
    except Exception as e:
        status_code = 500
        traceback.print_exc()
        print(f'error: {str(e)}')

    return transcript_dict(response), status_code

def transcript_dict(response):
    # Initial values of transcript, confidence and alternatives
    transcript = '_unknown_'
    confidence = 0.0
    alternatives = [[]]

    # Parsing the results of the ASR
    if response and hasattr(response, 'results'):
        for result in response.results:
            # The first alternative is the most likely one for this portion.
            if hasattr(result, 'alternatives') and result.alternatives:
                transcript = result.alternatives[0].transcript.lower()
                confidence = result.alternatives[0].confidence
        alternatives = parse_response(response)

    # Building the transcription dict
    return {
        "alternatives": alternatives,
        "transcript": transcript,
        "confidence": confidence
    }

def _parse_result(res):
    return [{
        "transcript": alt.transcript,
        "confidence": alt.confidence
    } for alt in res.alternatives]

def parse_response(response):
    """
    Parse response from GSpeech client and return a dictionary
    NOTE: We are not parsing word information from the alternatives
    """
    return [_parse_result(res) for res in response.results]

def main():
    audio_path = '../audio/some3.wav'
    audio_chunks = get_chunks(audio_path)

    result = transcribe_file(audio_chunks)
    pprint(result)

if __name__ == "__main__":
    main()