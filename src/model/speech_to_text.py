"""This script uses HuggingFace's Whisper model to transcribe
audio from an input file.

The user can specify the buffer time and offset time
to transcribe a specific portion of the audio file.
The user can also specify if they want to loop
over the audio file and transcribe it in chunks.
"""
import queue
from pathlib import Path
import argparse
import logging

from pythonosc import udp_client
from transformers import WhisperProcessor, WhisperForConditionalGeneration
import librosa
import sounddevice as sd

TARGET_SAMPLE_RATE = 16000
PROCESSOR = WhisperProcessor.from_pretrained("whispy/whisper_italian")
MODEL = WhisperForConditionalGeneration.from_pretrained("whispy/whisper_italian")

q = queue.Queue()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())


def callback(input_data, frames, time, status):
    """Callback function for the sounddevice stream.

    Args:
        input_data (ndarray): Input audio data
        status (int): Status of the sounddevice stream
    """

    if status:
        logger.error(f"Error: {status}")
    else:
        # Process the audio input
        logger.debug("Callback function called.")
        logger.debug("Put the audio input buffer into the queue.")
        q.put(input_data)


def load_audiofile(path: Path, start: int, duration: int) -> tuple:
    """Load audio file and return waveform and sample rate.

    Args:
        path (Path): Path to the audio file
        start (int): Start time in seconds
        duration (int): Duration in seconds

    Returns:
        tuple: waveform and sample rate
    """

    waveform, sample_rate = librosa.load(
        path=path,
        sr=TARGET_SAMPLE_RATE,
        offset=start,
        duration=duration,
        mono=True,
    )
    logger.info(f"Audio file loaded: {path}")
    logger.debug(f"Audio file shape: {waveform.shape}")

    return waveform, sample_rate


def transcribe(waveform, sample_rate) -> list:
    """Transcribe audio file.

    Args:
        waveform (ndarray): waveform of the audio file
        sample_rate (int): sample rate of the audio file

    Returns:
        list: list of token ids
    """

    input_features = PROCESSOR(
        waveform, sampling_rate=sample_rate, return_tensors="pt"
    ).input_features

    # generate token ids
    return MODEL.generate(input_features)


def send_to_output(result: str, osc_address: str):
    """Send the transcription result to the output.
    If the user specified an OSC address, send the result
    to that address. Otherwise, log the result.

    Args:
        result (str): The transcription result
        osc_address (str): The address of the OSC client
    """
    if result:
        if osc_address:
            osc_client = udp_client.SimpleUDPClient(osc_address, 8080)
            osc_client.send_message("/speech", result)
            logger.info(f"Sent to {osc_address}: {result}")
        else:
            logger.info(result)


def transcribe_stream():
    """Transcribe audio input from the stream.
    The audio input is stored and processed in a queue.
    The queue is emptied and transcribed every time.

    Returns:
        str: The transcription result
    """

    try:
        data = q.get_nowait()
        logger.debug("Transcribing audio input...")
        predicted_ids = transcribe(data.reshape(-1), TARGET_SAMPLE_RATE)
        transcription = PROCESSOR.batch_decode(predicted_ids, skip_special_tokens=True)[
            0
        ]
        logger.debug("Transcription result:")
        logger.debug(transcription)

        return transcription
    except queue.Empty:
        pass


def setup_stream(**kwargs) -> sd.InputStream:
    """Setup the sounddevice InputStream.

    Returns:
        sd.InputStream: The sounddevice InputStream
        to capture audio input.
    """

    logger.info("Scan for audio devices:")
    logger.info(sd.query_devices())
    sd.default.device = "BlackHole 2ch"
    logger.info(f"Input device: {sd.default.device}")
    logger.info(f"Sample rate: {TARGET_SAMPLE_RATE}")
    logger.info("Capturing audio. Press Ctrl+C to stop.")
    logger.info(f"Buffer size (s): {kwargs.get('buffer_size')}")
    return sd.InputStream(
        device=sd.default.device,
        channels=1,
        samplerate=TARGET_SAMPLE_RATE,
        callback=callback,
        blocksize=TARGET_SAMPLE_RATE * kwargs["buffer_size"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Speech to text transcription using HuggingFace's Whisper model"
    )

    # Arguments required for both modes
    parser.add_argument(
        "--input",
        choices=["stream", "file"],
        required=True,
        help="The mode of input, e.g. stream or file",
    )
    # Arguments required for input file
    file_args = parser.add_argument_group()
    file_args.add_argument(
        "--input-file", type=str, help="Path to the input audio file"
    )
    file_args.add_argument("--offset", type=int, help="Offset time in seconds")
    file_args.add_argument(
        "--loop",
        action="store_true",
        help="Loop over the audio file and transcribe it in chunks",
    )
    file_args.add_argument("--buffer", type=int, help="Buffer time in seconds")
    # Arguments required for input stream
    stream_args = parser.add_argument_group()
    stream_args.add_argument(
        "--buffer-size",
        type=int,
        help="Transcription buffer size in seconds",
    )

    # Arguments required for output in both modes
    parser.add_argument("--osc-address", type=str, help="The address of the OSC client")

    args = parser.parse_args()
    logger.info(f"Arguments: {args}")

    match args.input:
        case "stream":
            try:
                with setup_stream(buffer_size=args.buffer_size):
                    while True:
                        send_to_output(transcribe_stream(), args.osc_address)
            except KeyboardInterrupt:
                logger.info("\nInterrupted by user")
                parser.exit(0)
            except TypeError:
                logger.error("Please specify a buffer size.")
                parser.exit(1)
        case "file":
            audiofile = args.input_file
            buffer_time = args.buffer
            offset = args.offset
            loop = args.loop

            file_path = Path(audiofile).resolve()
            match loop:
                case True:
                    while True:
                        predicted_ids = transcribe(
                            # The * operator unpacks the tuple
                            *load_audiofile(file_path, offset, buffer_time)
                        )

                        send_to_output(
                            PROCESSOR.batch_decode(
                                predicted_ids, skip_special_tokens=True
                            ),
                            args.osc_address,
                        )
                        # update offset
                        offset += buffer_time
                case False:
                    predicted_ids = transcribe(
                        # The * operator unpacks the tuple
                        *load_audiofile(file_path, offset, buffer_time)
                    )
                    send_to_output(
                        PROCESSOR.batch_decode(predicted_ids, skip_special_tokens=True),
                        args.osc_address,
                    )


if __name__ == "__main__":
    main()
