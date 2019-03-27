import os
import json
import shutil
from typing import Dict, List

from flask import Flask, request
from celery import Celery
from pydub import AudioSegment
from pydub.silence import split_on_silence

import tdnn_decode
import utils

CELERY_BROKER_URL = 'redis://{}:6379/{}'.format(
    os.environ.get('REDIS_HOST', 'localhost'),
    os.environ.get('REDIS_VIRTUAL_PORT', '0')
)
REDIS_EXPIRY_TIME = 10800   # 3hrs

flask_app = Flask("kaldi-serve")
celery = Celery('asr-server', broker=CELERY_BROKER_URL)
celery.conf.update(
    task_routes={
        'preprocess-task': {'queue': 'preprocess'},
        'asr-task': {'queue': 'asr'},
        'asr-complete-task': {'queue': 'preprocess'},
    },
)

config = {
    "en": {
        "word_syms_filename": "models/english/s5/exp/chain/tree_a_sp/graph/words.txt",
        "model_in_filename" : "models/english/s5/exp/chain/tdnn1g_sp_online/final.mdl",
        "fst_in_str"        : "models/english/s5/exp/chain/tree_a_sp/graph/HCLG.fst",
        "mfcc_config"       : "models/english/s5/exp/chain/tdnn1g_sp_online/conf/mfcc.conf",
        "ie_conf_filename"  : "models/english/s5/exp/chain/tdnn1g_sp_online/conf/ivector_extractor.conf",
    },
    "hi": {
        "word_syms_filename": "models/hindi/exp/chain/tree_a_sp/graph/words.txt",
        "model_in_filename" : "models/hindi/exp/chain/tdnn1g_sp_online/final.mdl",
        "fst_in_str"        : "models/hindi/exp/chain/tree_a_sp/graph/HCLG.fst",
        "mfcc_config"       : "models/hindi/exp/chain/tdnn1g_sp_online/conf/mfcc.conf",
        "ie_conf_filename"  : "models/hindi/exp/chain/tdnn1g_sp_online/conf/ivector_extractor.conf",
    }
}

en_model = None
hi_model = None

def copy_models():
    if not os.path.exists("/home/app/models"):
        try:
            shutil.copytree("/vol/data/models", "/home/app/models")
        except OSError as e:
            print('models not copied. Error: %s' % e)

@celery.task(name="asr-task")
def run_asr_async(operation_name: str, audio_uri: str, config: Dict):
    """
    :param operation_name: job id for this process
    :param audio_uri: audio url to read from [path to file on NFS]
    :param config:
                {
                    "language_code": "hi",
                    "sample_rate_hertz":"16000",
                    "encoding": "LINEAR16"
                }
    """
    copy_models()

    results, error = transcribe(audio_uri, config["language_code"], operation_name)

    celery.send_task('asr-complete-task', kwargs={
        'operation_name': operation_name,
        'results': results,
        'error': error
    })


@flask_app.route('/run-asr/', methods=['POST'])
def run_asr_sync():
    """
    post data:
    {
    operation_name: "xxxx",
    audio_uri: "[PATH-TO-NFS]"
    config: {
            "language_code": "hi",
            "sample_rate_hertz":"16000",
            "encoding": "LINEAR16"
            }
    }
    """
    copy_models()
    data = request.get_json()

    # start the process here
    language_code = data["config"]["language_code"]
    results, error = transcribe(data["audio_uri"], language_code, data["operation_name"])

    return json.dumps({"results": results, "error": error})


def get_model(lang: str, config: Dict):
    if lang == "en":
        global en_model
        if not en_model:
            en_model = tdnn_decode.load_model(
                13.0, 7000, 200, 6.0, 1.0, 3,
                config["word_syms_filename"], config["model_in_filename"],
                config["fst_in_str"], config["mfcc_config"], config["ie_conf_filename"]
            )
        return en_model
    else:
        global hi_model
        if not hi_model:
            hi_model = tdnn_decode.load_model(
                13.0, 7000, 200, 6.0, 1.0, 3, config["word_syms_filename"],
                config["model_in_filename"], config["fst_in_str"],
                config["mfcc_config"], config["ie_conf_filename"]
            )
        return hi_model


def transcribe(audio_uri: str, lang: str, operation_name:str) -> (List[str], str):
    """
    Transcribe audio
    """
    try:
        chunks = utils.get_chunks(audio_uri)

        transcriptions = []
        for i, chunk in enumerate(chunks):
            # write chunk to file
            chunk_filename = "/home/%s_chunk_%s.wav" % (operation_name, i)
            chunk.export(chunk_filename, format="wav")

            # load model
            config_obj = config[lang]
            _model = get_model(lang, config_obj)

            # call infer
            transcription, confidence = tdnn_decode.infer(_model, chunk_filename)
            transcriptions.append({
                "alternatives": [
                    {
                        "transcript": transcription,
                        "confidence": confidence,
                    },
                ]
            })
    except Exception as e:
        return [], str(e)
    return transcriptions, None


if __name__ == '__main__':
    flask_app.run(host="0.0.0.0", port="8002")
