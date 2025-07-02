from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import requests
import speech_recognition as sr
import asyncio
import edge_tts
import os
from langdetect import detect
from .models import Conversation
import json
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import Tool

# Ollama 설정
OLLAMA_URL = "http://host.docker.internal:11434/api/generate"
OLLAMA_MODEL = "llama3"

# Neo 프롬프트 튜닝
NEO_PROMPT = (
    "너의 이름은 Neo야. 너는 다정하고 친절하며 유머러스한 AI 비서야. "
    "늘 존댓말로 대답하도록 해."
    "항상 따뜻하고 재치 있게 대답해줘. 단, 이모티콘은 절대 사용하지 마. "
    "사용자가 힘들거나 고민이 있을 때는 진심 어린 위로와 함께, 상황에 맞는 유머로 분위기를 밝게 해줘. "
    "모든 답변은 반드시 자연스러운 한국어로 해줘."

    "너는 프론트엔드 개발자 황수민이 만든 llama3 기반 AI 비서야."
    "너는 아직 개발중에 있어."
    "@Web을 붙여서 질문하면 웹에서 검색할 수 있어."
)

# DuckDuckGo 웹 검색 도구 인스턴스 생성
duckduckgo_search = DuckDuckGoSearchRun()

def ask_ollama(prompt, model=OLLAMA_MODEL, enable_web_search=False):
    """Ollama API를 통해 LLM에 질문, 필요시 웹 검색 결과 포함"""
    web_search_result = ""
    if enable_web_search:
        try:
            web_search_result = duckduckgo_search.run(prompt)
        except Exception as e:
            web_search_result = f"[웹 검색 오류: {e}]"
    
    full_prompt = f"{NEO_PROMPT}\n\n사용자: {prompt}\n"
    if web_search_result:
        full_prompt += f"\n[웹 검색 결과]\n{web_search_result}\n"
    full_prompt += "Neo:"
    data = {"model": model, "prompt": full_prompt, "stream": False}
    try:
        response = requests.post(OLLAMA_URL, json=data)
        response.raise_for_status()
        return response.json().get("response", "답변을 가져오지 못했습니다.")
    except Exception as e:
        return f"Ollama와 통신 중 오류 발생: {e}"

def speak_text(text):
    """텍스트를 음성으로 변환"""
    try:
        lang = detect(text)
    except Exception:
        lang = 'ko'

    if lang == 'en':
        voice = "en-US-GuyNeural"
    else:
        voice = "ko-KR-InJoonNeural"

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

@csrf_exempt
@require_http_methods(["POST"])
def chat_api(request):
    """채팅 API 엔드포인트"""
    try:
        data = json.loads(request.body)
        user_input = data.get('message', '')
        # 메시지 앞에 @Web이 있으면 웹 검색 활성화
        enable_web_search = False
        if user_input.strip().startswith('@Web'):
            enable_web_search = True
            user_input = user_input.strip()[4:].lstrip()  # @Web 제거 후 앞 공백 제거
        else:
            enable_web_search = data.get('web_search', False)
        if not user_input:
            return JsonResponse({'error': '메시지가 비어있습니다.'}, status=400)
        # LLM에 질문 (웹 검색 옵션 추가)
        ai_response = ask_ollama(user_input, enable_web_search=enable_web_search)
        # 대화 기록 저장
        Conversation.objects.create(
            user_input=user_input,
            ai_response=ai_response
        )
        return JsonResponse({
            'response': ai_response,
            'timestamp': Conversation.objects.latest('timestamp').timestamp.isoformat()
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def voice_chat_api(request):
    """음성 채팅 API 엔드포인트"""
    try:
        # 음성 파일 처리 (실제 구현에서는 파일 업로드 처리 필요)
        # 여기서는 텍스트 입력을 받는다고 가정
        data = json.loads(request.body)
        user_input = data.get('message', '')
        
        if not user_input:
            return JsonResponse({'error': '음성 메시지가 비어있습니다.'}, status=400)
        
        # LLM에 질문
        ai_response = ask_ollama(user_input)
        
        # 대화 기록 저장
        Conversation.objects.create(
            user_input=user_input,
            ai_response=ai_response
        )
        
        # 음성 출력 (선택사항)
        speak_text(ai_response)
        
        return JsonResponse({
            'response': ai_response,
            'timestamp': Conversation.objects.latest('timestamp').timestamp.isoformat()
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def chat_history(request):
    """대화 기록 조회"""
    conversations = Conversation.objects.all()[:50]  # 최근 50개
    return JsonResponse({
        'conversations': list(conversations.values('user_input', 'ai_response', 'timestamp'))
    })

def home(request):
    """홈페이지"""
    return render(request, 'assistant/home.html')
