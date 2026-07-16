from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers


class UserSerializer(serializers.ModelSerializer):
    """Shaped to match the Flutter AuthUser.fromJson() parser:
    { id, email, name, avatar_url }
    """
    name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "name", "avatar_url"]

    def get_name(self, obj):
        full_name = obj.get_full_name()
        return full_name or obj.username

    def get_avatar_url(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.avatar_url if profile else None


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
