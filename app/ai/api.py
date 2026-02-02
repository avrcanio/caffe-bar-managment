from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AIQueryLog
from .services import handle_ai_query


class AIQuerySerializer(serializers.Serializer):
    question = serializers.CharField()


class AIQueryView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AIQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data["question"]

        log = AIQueryLog.objects.create(user=request.user, question=question)

        try:
            answer, tool_results = handle_ai_query(question)
            log.response_text = answer
            log.tool_calls = [
                {
                    "name": item.name,
                    "arguments": item.arguments,
                    "result": item.result,
                }
                for item in tool_results
            ]
            log.status = AIQueryLog.STATUS_OK
            log.save(update_fields=["response_text", "tool_calls", "status"])
            return Response(
                {
                    "answer": answer,
                    "tools": log.tool_calls,
                }
            )
        except Exception as exc:
            log.status = AIQueryLog.STATUS_ERROR
            log.error_message = str(exc)
            log.save(update_fields=["status", "error_message"])
            return Response(
                {"error": "AI upit nije uspio.", "details": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
