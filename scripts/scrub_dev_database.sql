-- Sever a restored production database from live users. Run only on the dev pod.
TRUNCATE TABLE django_session;
DELETE FROM api_emailverificationcode;
DELETE FROM api_passwordresetcode;
UPDATE auth_user SET password = '!' WHERE password IS NOT NULL;
UPDATE api_profile SET stripe_customer_id = '', stripe_subscription_id = '';
UPDATE auth_user SET email = 'user-' || id || '@dev.invalid';
UPDATE core_prayerrequest SET email = 'prayer-' || id || '@dev.invalid' WHERE email <> '';
