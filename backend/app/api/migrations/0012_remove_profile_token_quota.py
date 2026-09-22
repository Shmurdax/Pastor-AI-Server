# Drop Premium chat token budgets (wallet, daily pacing, and admin cooldowns).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0011_profile_token_cycle_anchor"),
    ]

    operations = [
        migrations.RemoveField(model_name="profile", name="token_balance"),
        migrations.RemoveField(model_name="profile", name="tokens_spent"),
        migrations.RemoveField(model_name="profile", name="token_period_key"),
        migrations.RemoveField(model_name="profile", name="token_cycle_anchor"),
        migrations.RemoveField(model_name="profile", name="tokens_used_today"),
        migrations.RemoveField(model_name="profile", name="token_usage_day"),
        migrations.RemoveField(model_name="profile", name="token_cooldown_until"),
    ]
