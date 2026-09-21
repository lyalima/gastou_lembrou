from django.contrib import admin

from .models import (
    AssistantConversation,
    AssistantKnowledgeChunk,
    AssistantKnowledgeDocument,
    AssistantMessage,
    GoogleCalendarConnection,
    PaymentCalendarEvent,
)


@admin.register(AssistantConversation)
class AssistantConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "created_at", "updated_at", "closed_at")
    list_filter = ("status", "created_at", "updated_at")
    search_fields = ("user__email",)
    readonly_fields = ("id", "created_at", "updated_at", "closed_at")


@admin.register(AssistantMessage)
class AssistantMessageAdmin(admin.ModelAdmin):
    list_display = ("user", "conversation", "role", "intent", "created_at")
    list_filter = ("role", "intent", "created_at")
    search_fields = ("user__email", "content")
    readonly_fields = ("created_at",)


class AssistantKnowledgeChunkInline(admin.TabularInline):
    model = AssistantKnowledgeChunk
    extra = 0
    fields = ("position", "heading", "content", "embedding")
    readonly_fields = fields
    can_delete = False


@admin.register(AssistantKnowledgeDocument)
class AssistantKnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "version", "is_active", "synced_at")
    list_filter = ("is_active", "version")
    search_fields = ("title", "source_path")
    readonly_fields = ("slug", "source_path", "checksum", "synced_at")
    inlines = (AssistantKnowledgeChunkInline,)


@admin.register(GoogleCalendarConnection)
class GoogleCalendarConnectionAdmin(admin.ModelAdmin):
    list_display = ("user", "google_email", "is_active", "token_expires_at", "updated_at")
    list_filter = ("is_active", "created_at", "updated_at")
    search_fields = ("user__email", "google_email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(PaymentCalendarEvent)
class PaymentCalendarEventAdmin(admin.ModelAdmin):
    list_display = ("user", "payment", "scheduled_for", "status", "updated_at")
    list_filter = ("status", "scheduled_for", "created_at")
    search_fields = ("user__email", "payment__title", "google_event_id")
    readonly_fields = ("created_at", "updated_at")
