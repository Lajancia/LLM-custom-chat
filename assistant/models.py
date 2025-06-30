from django.db import models

# Create your models here.

class Conversation(models.Model):
    user_input = models.TextField(verbose_name="사용자 입력")
    ai_response = models.TextField(verbose_name="AI 응답")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="대화 시간")
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = "대화 기록"
        verbose_name_plural = "대화 기록들"
    
    def __str__(self):
        return f"{self.timestamp.strftime('%Y-%m-%d %H:%M')} - {self.user_input[:50]}"
