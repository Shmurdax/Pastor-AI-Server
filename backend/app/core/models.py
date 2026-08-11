from django.db import models

class ChatMessage(models.Model):
    # session_id allows different Flutter users to have separate memories
    session_id = models.TextField()
    # Linked login account when the Flutter client sends a DRF auth token.
    # Null for anonymous / not-logged-in chatters.
    user = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="chat_messages",
    )
    user_query = models.TextField()
    ai_response = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Indexing the session_id and timestamp makes the "Sliding Window" query very fast
        indexes = [
            models.Index(fields=['session_id', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.session_id}: {self.user_query[:20]}"


class IngestedDocument(models.Model):
    source_name = models.CharField(max_length=255)
    title = models.CharField(
        max_length=300,
        help_text="Display name for links and APIs (defaults from filename; edit to match sermon titles in your app).",
    )
    file_hash = models.CharField(max_length=64, unique=True)
    original_extension = models.CharField(max_length=10)
    chunk_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.title} — {self.source_name} ({self.file_hash[:10]})"


class IngestedChunk(models.Model):
    document = models.ForeignKey(
        IngestedDocument,
        related_name="chunks",
        on_delete=models.CASCADE,
    )
    chunk_hash = models.CharField(max_length=64, unique=True)
    qdrant_point_id = models.CharField(max_length=36, unique=True)
    source_name = models.CharField(max_length=255)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["source_name"], name="core_ingest_source__54860e_idx"),
            models.Index(fields=["created_at"], name="core_ingest_created_926434_idx"),
        ]

    def __str__(self):
        return f"{self.source_name}#{self.position}"


class IngestionJob(models.Model):
    STATUS_CHOICES = [
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    started_by = models.CharField(max_length=150)
    replace_existing_sources = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    files_received = models.PositiveIntegerField(default=0)
    files_processed = models.PositiveIntegerField(default=0)
    files_skipped_as_duplicates = models.PositiveIntegerField(default=0)
    files_failed = models.PositiveIntegerField(default=0)
    chunks_created = models.PositiveIntegerField(default=0)
    chunks_skipped_as_duplicates = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Job {self.id} ({self.status})"


class IngestionJobLog(models.Model):
    job = models.ForeignKey(IngestionJob, related_name="logs", on_delete=models.CASCADE)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Job {self.job_id} log"


class IngestionJobFileFailure(models.Model):
    job = models.ForeignKey(IngestionJob, related_name="file_failures", on_delete=models.CASCADE)
    original_name = models.CharField(max_length=512)
    error_message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["job", "created_at"], name="core_ingest_job_id_2c4137_idx"),
        ]

    def __str__(self):
        return f"Job {self.job_id} failed: {self.original_name}"


class PrayerRequest(models.Model):
    """Prayer form submissions from the Flutter frontend."""

    name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    prayer_text = models.TextField()
    is_anonymous = models.BooleanField(default=False)
    user = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    followed_up = models.BooleanField(default=False)
    pastor_notes = models.TextField(blank=True)
    contacted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        if self.is_anonymous:
            return f"Anonymous prayer ({self.created_at:%Y-%m-%d})"
        label = self.name or self.email or "Unknown"
        return f"Prayer from {label} ({self.created_at:%Y-%m-%d})"


class ChurchEvent(models.Model):
    """Public church calendar events (staff-managed)."""

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=300)
    host_name = models.CharField(
        max_length=200,
        help_text="Person or ministry hosting the event.",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    is_published = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="church_events_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at", "title"]

    def __str__(self):
        return f"{self.title} ({self.starts_at:%Y-%m-%d})"

