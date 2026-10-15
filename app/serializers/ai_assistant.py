from rest_framework import serializers

MAX_HISTORY_MESSAGES = 20


class AIAssistantHistoryMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["user", "assistant"])
    content = serializers.CharField(max_length=2000, trim_whitespace=True, allow_blank=False)


class AIAssistantChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000, trim_whitespace=True, allow_blank=False)
    # Prior turns of this conversation, oldest first, so the assistant has memory of
    # what was already asked/answered. Only the most recent MAX_HISTORY_MESSAGES are kept.
    history = AIAssistantHistoryMessageSerializer(many=True, required=False, default=list)

    def validate_history(self, value):
        return value[-MAX_HISTORY_MESSAGES:]


class AIAssistantChatResponseSerializer(serializers.Serializer):
    reply = serializers.CharField()
