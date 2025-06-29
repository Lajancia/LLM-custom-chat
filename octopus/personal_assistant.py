import requests
import speech_recognition as sr
import pyttsx3
import platform
import importlib.util
import os
import asyncio
import edge_tts
from langdetect import detect

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"  # 현재 사용 중인 모델명으로 변경

# TTS_MODE: 'pyttsx3', 'say', 'coqui' 중 선택. 'auto'는 자동 감지
TTS_MODE = 'say'

# 프롬프트 튜닝: Neo의 성격/역할
NEO_PROMPT = (
    "너의 이름은 Neo야."
)

def ask_ollama(prompt, model=OLLAMA_MODEL):
    # 프롬프트 튜닝 적용
    full_prompt = f"{NEO_PROMPT}\n\n사용자: {prompt}\nNeo:"
    data = {"model": model, "prompt": full_prompt, "stream": False}
    try:
        response = requests.post(OLLAMA_URL, json=data)
        response.raise_for_status()
        return response.json().get("response", "답변을 가져오지 못했습니다.")
    except Exception as e:
        return f"Ollama와 통신 중 오류 발생: {e}"

def listen_microphone():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("마이크를 준비 중입니다...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        recognizer.pause_threshold = 2.0  # 말이 멈춘 뒤 2초 후에 인식 종료
        print("질문을 시작하세요. (말이 끝나면 2초 후 자동으로 인식합니다)")
        audio = recognizer.listen(source)
    try:
        question = recognizer.recognize_google(audio, language="ko-KR")
        print(f"질문: {question}")
        return question
    except sr.UnknownValueError:
        print("음성을 인식하지 못했습니다.")
        return None
    except sr.RequestError as e:
        print(f"음성 인식 서비스 오류: {e}")
        return None

def speak(text):
    # 언어 감지
    try:
        lang = detect(text)
    except Exception:
        lang = 'ko'  # 감지 실패 시 기본값

    if lang == 'en':
        voice = "en-US-GuyNeural"  # 영어 남성
    else:
        voice = "ko-KR-InJoonNeural"  # 한국어 남성

    async def _speak():
        communicate = edge_tts.Communicate(text, voice=voice)
        await communicate.save("output.mp3")
        os.system("afplay output.mp3")
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import nest_asyncio
        nest_asyncio.apply()
        asyncio.ensure_future(_speak())
    else:
        asyncio.run(_speak())

def main():
    EXIT_KEYWORDS = [
        "종료", "끝", "exit", "quit",
        "그만", "그만할래", "이만할게", "이만 대화를 마칠게", "여기까지 할게", "대화 종료", "그만둘래"
    ]
    try:
        while True:
            question = listen_microphone()
            if not question:
                continue
            if any(keyword in question.strip().lower() for keyword in EXIT_KEYWORDS):
                print("비서를 종료합니다.")
                break
            answer = ask_ollama(question)
            print(f"답변: {answer}")
            speak(answer)
    except KeyboardInterrupt:
        print("\n비서를 종료합니다.")

if __name__ == "__main__":
    main() 