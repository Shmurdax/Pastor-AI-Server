from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from core.models import PrayerRequest, ChurchEvent


class UserSerializer(serializers.ModelSerializer):
    """Shaped to match the Flutter AuthUser.fromJson() parser:
    { id, email, name, avatar_url, is_staff, is_premium, subscription_status,
      billing_period, cancel_at_period_end, current_period_end }
    """
    name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    is_premium = serializers.SerializerMethodField()
    subscription_status = serializers.SerializerMethodField()
    billing_period = serializers.SerializerMethodField()
    cancel_at_period_end = serializers.SerializerMethodField()
    current_period_end = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "name",
            "avatar_url",
            "is_staff",
            "is_premium",
            "subscription_status",
            "billing_period",
            "cancel_at_period_end",
            "current_period_end",
        ]

    def get_name(self, obj):
        full_name = obj.get_full_name()
        return full_name or obj.username

    def get_avatar_url(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.avatar_url if profile else None

    def _profile(self, obj):
        profile = getattr(obj, "profile", None)
        if profile is not None:
            profile.expire_canceled_subscription_if_needed()
        return profile

    def get_is_premium(self, obj):
        # Staff accounts receive the same entitlements as paid Premium members.
        if obj.is_staff or obj.is_superuser:
            return True
        profile = self._profile(obj)
        return bool(profile and profile.is_premium)

    def get_subscription_status(self, obj):
        profile = self._profile(obj)
        return profile.subscription_status if profile else "free"

    def get_billing_period(self, obj):
        profile = self._profile(obj)
        return profile.billing_period if profile else ""

    def get_cancel_at_period_end(self, obj):
        profile = self._profile(obj)
        return bool(profile and profile.cancel_at_period_end)

    def get_current_period_end(self, obj):
        profile = self._profile(obj)
        if not profile or profile.current_period_end is None:
            return None
        return profile.current_period_end.isoformat()


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_email(self, value):
        value = value.lower().strip()
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_password(self, value):
        # Runs Django's built-in password strength checks
        validate_password(value)
        return value

    def create(self, validated_data):
        name = validated_data["name"].strip()
        email = validated_data["email"]
        password = validated_data["password"]

        first_name, _, last_name = name.partition(" ")
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class GoogleAuthSerializer(serializers.Serializer):
    """Flutter AuthService.signInWithGoogle() posts { "id_token": "..." }."""
    id_token = serializers.CharField()


class PrayerRequestSerializer(serializers.ModelSerializer):
    submitter_user_email = serializers.SerializerMethodField()
    submitter_user_name = serializers.SerializerMethodField()

    class Meta:
        model = PrayerRequest
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "prayer_text",
            "is_anonymous",
            "created_at",
            "followed_up",
            "pastor_notes",
            "contacted_at",
            "submitter_user_email",
            "submitter_user_name",
        ]
        read_only_fields = [
            "id",
            "name",
            "email",
            "phone",
            "prayer_text",
            "is_anonymous",
            "created_at",
            "followed_up",
            "pastor_notes",
            "contacted_at",
        ]

    def get_submitter_user_email(self, obj):
        if obj.user_id is None:
            return None
        return obj.user.email

    def get_submitter_user_name(self, obj):
        if obj.user_id is None:
            return None
        full = obj.user.get_full_name()
        return full or obj.user.username


class PrayerRequestStaffUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrayerRequest
        fields = ["followed_up", "pastor_notes", "contacted_at"]


class ChurchEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChurchEvent
        fields = [
            "id",
            "title",
            "description",
            "location",
            "host_name",
            "starts_at",
            "ends_at",
            "is_published",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ChurchEventWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChurchEvent
        fields = [
            "title",
            "description",
            "location",
            "host_name",
            "starts_at",
            "ends_at",
            "is_published",
        ]

    def validate(self, attrs):
        starts = attrs.get("starts_at") or getattr(self.instance, "starts_at", None)
        ends = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts and ends and ends < starts:
            raise serializers.ValidationError({"ends_at": "End time must be after start time."})
        return attrs

