import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


def attach_existing_messages(apps, schema_editor):
    Conversation = apps.get_model("assistant", "AssistantConversation")
    Message = apps.get_model("assistant", "AssistantMessage")
    # Remove AssistantMessage's default ordering so PostgreSQL applies DISTINCT
    # only to user_id. Otherwise created_at is added to SELECT and one user can
    # incorrectly produce multiple active conversations.
    user_ids = (
        Message.objects.filter(conversation__isnull=True)
        .order_by()
        .values_list("user_id", flat=True)
        .distinct()
    )
    for user_id in user_ids.iterator():
        conversation, _ = Conversation.objects.get_or_create(user_id=user_id, status="active")
        Message.objects.filter(user_id=user_id, conversation__isnull=True).update(conversation=conversation)


def detach_existing_messages(apps, schema_editor):
    Message = apps.get_model("assistant", "AssistantMessage")
    Conversation = apps.get_model("assistant", "AssistantConversation")
    Message.objects.update(conversation=None)
    Conversation.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AssistantConversation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("active", "Ativa"), ("closed", "Encerrada")], default="active", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assistant_conversations", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-updated_at",)},
        ),
        migrations.CreateModel(
            name="AssistantKnowledgeDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(max_length=120, unique=True)),
                ("title", models.CharField(max_length=180)),
                ("source_path", models.CharField(max_length=255, unique=True)),
                ("version", models.CharField(default="1.0", max_length=32)),
                ("checksum", models.CharField(max_length=64)),
                ("is_active", models.BooleanField(default=True)),
                ("synced_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("title",)},
        ),
        migrations.CreateModel(
            name="AssistantKnowledgeChunk",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("heading", models.CharField(blank=True, max_length=220)),
                ("content", models.TextField()),
                ("position", models.PositiveIntegerField()),
                ("embedding", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chunks", to="assistant.assistantknowledgedocument")),
            ],
            options={"ordering": ("document", "position")},
        ),
        migrations.AddField(
            model_name="assistantmessage",
            name="conversation",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="assistant.assistantconversation"),
        ),
        migrations.RunPython(attach_existing_messages, detach_existing_messages),
        migrations.AddConstraint(
            model_name="assistantconversation",
            constraint=models.UniqueConstraint(condition=models.Q(("status", "active")), fields=("user",), name="unique_active_spike_conversation_per_user"),
        ),
        migrations.AddConstraint(
            model_name="assistantknowledgechunk",
            constraint=models.UniqueConstraint(fields=("document", "position"), name="unique_spike_chunk_position"),
        ),
    ]
