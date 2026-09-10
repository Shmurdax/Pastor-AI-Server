/// Localized UI copy for the display page (chat, nav, sermon library, prayer).
///
/// Keep keys stable; fall back to English when a translation is missing.
class AppStrings {
  AppStrings(this.languageCode);

  final String languageCode;

  String get home => _t('home');
  String get store => _t('store');
  String get events => _t('events');
  String get nordinsAi => _t('nordinsAi');
  String get chat => _t('chat');
  String get media => _t('media');
  String get subscribe => _t('subscribe');
  String get prayerInbox => _t('prayerInbox');
  String get language => _t('language');

  String get sermons => _t('sermons');
  String get chats => _t('chats');
  String get sermonLibrary => _t('sermonLibrary');
  String get sermonLibraryEmpty => _t('sermonLibraryEmpty');
  String get lastQuestionSources => _t('lastQuestionSources');
  String get previousChats => _t('previousChats');
  String get newChat => _t('newChat');
  String get historyEmptySignedIn => _t('historyEmptySignedIn');
  String get historyEmptyGuest => _t('historyEmptyGuest');
  String get historyHintFree => _t('historyHintFree');
  String get historyHintGuest => _t('historyHintGuest');
  String get conversation => _t('conversation');
  String get newConversation => _t('newConversation');
  String get deleteChat => _t('deleteChat');
  String get deleteChatTitle => _t('deleteChatTitle');
  String deleteChatBody(String title) =>
      _t('deleteChatBody').replaceAll('{title}', title);
  String get cancel => _t('cancel');
  String get delete => _t('delete');
  String get chatDeleted => _t('chatDeleted');

  String get welcomeTitle => _t('welcomeTitle');
  String get welcomeBody => _t('welcomeBody');
  String get howCanIHelp => _t('howCanIHelp');
  String get listeningHint => _t('listeningHint');
  String get askWithVoice => _t('askWithVoice');
  String get stopVoiceInput => _t('stopVoiceInput');
  String get backToBottom => _t('backToBottom');
  String get copyToClipboard => _t('copyToClipboard');
  String get regenerateResponse => _t('regenerateResponse');
  String sermonSourcesCount(int count) =>
      _t('sermonSourcesCount').replaceAll('{n}', '$count');
  String get copiedToClipboard => _t('copiedToClipboard');
  String get responseCancelled => _t('responseCancelled');
  String get serverError => _t('serverError');
  String couldNotOpenSource(String stem) =>
      _t('couldNotOpenSource').replaceAll('{stem}', stem);

  String get prayerRequestForm => _t('prayerRequestForm');
  String get prayerRequest => _t('prayerRequest');
  String get prayerReceived => _t('prayerReceived');
  String get prayerTeamLifting => _t('prayerTeamLifting');
  String get sharePrayerNeed => _t('sharePrayerNeed');
  String get submitAnonymously => _t('submitAnonymously');
  String get name => _t('name');
  String get email => _t('email');
  String get phoneOptional => _t('phoneOptional');
  String get yourPrayerRequest => _t('yourPrayerRequest');
  String get enterYourName => _t('enterYourName');
  String get enterYourEmail => _t('enterYourEmail');
  String get enterValidEmail => _t('enterValidEmail');
  String get prayerTooShort => _t('prayerTooShort');
  String get submitPrayerRequest => _t('submitPrayerRequest');
  String get prayerSubmitFailed => _t('prayerSubmitFailed');

  String get signInToSave => _t('signInToSave');
  String get signIn => _t('signIn');
  String signedInAs(String name) => _t('signedInAs').replaceAll('{name}', name);
  String get signedOut => _t('signedOut');
  String get translatingReplies => _t('translatingReplies');

  String _t(String key) {
    final table = _tables[languageCode] ?? _tables['en']!;
    return table[key] ?? _tables['en']![key] ?? key;
  }
}

const Map<String, Map<String, String>> _tables = {
  'en': {
    'home': 'Home',
    'store': 'Store',
    'events': 'Events',
    'nordinsAi': "NORDIN'S AI",
    'chat': 'Chat',
    'media': 'Media',
    'subscribe': 'Subscribe',
    'prayerInbox': 'Prayer inbox',
    'language': 'Language',
    'sermons': 'Sermons',
    'chats': 'Chats',
    'sermonLibrary': 'Sermon Library',
    'sermonLibraryEmpty':
        'Relevant sermons will appear here after you ask a question.',
    'lastQuestionSources': "Last Question's Sources",
    'previousChats': 'Previous Chats',
    'newChat': 'New Chat',
    'historyEmptySignedIn':
        'Your saved chats will appear here. Start a conversation to build history.',
    'historyEmptyGuest':
        'Your most recent chat is saved here. Upgrade to Premium for unlimited history.',
    'historyHintFree': 'Free plan: only your most recent chat is kept.',
    'historyHintGuest':
        'Guest: only your most recent chat is kept. Sign in & go Premium for unlimited history.',
    'conversation': 'Conversation',
    'newConversation': 'New conversation',
    'deleteChat': 'Delete chat',
    'deleteChatTitle': 'Delete chat?',
    'deleteChatBody':
        'Remove “{title}” from your history? This cannot be undone.',
    'cancel': 'Cancel',
    'delete': 'Delete',
    'chatDeleted': 'Chat deleted',
    'welcomeTitle': "Welcome to the Nordin's AI Assistant",
    'welcomeBody':
        "This tool is trained on Pastor Don's sermon notes and resources. The AI may occasionally produce inaccurate information. Please verify insights with your Bible.",
    'howCanIHelp': 'How can I help you?',
    'listeningHint': 'Listening… speak your question',
    'askWithVoice': 'Ask with voice',
    'stopVoiceInput': 'Stop voice input',
    'backToBottom': 'Back to bottom',
    'sermonSourcesCount': 'Sermon sources ({n})',
    'copyToClipboard': 'Copy to clipboard',
    'regenerateResponse': 'Regenerate response',
    'copiedToClipboard': 'Copied to clipboard!',
    'responseCancelled': '_Response cancelled by user._',
    'serverError': 'Error: Could not connect to the server.',
    'couldNotOpenSource': 'Could not open source for "{stem}".',
    'prayerRequestForm': 'Prayer Request Form',
    'prayerRequest': 'Prayer Request',
    'prayerReceived': 'Your prayer request has been received.',
    'prayerTeamLifting': 'Our prayer team will be lifting you up.',
    'sharePrayerNeed': 'Share your prayer need with us.',
    'submitAnonymously': 'Submit anonymously',
    'name': 'Name',
    'email': 'Email',
    'phoneOptional': 'Phone (optional)',
    'yourPrayerRequest': 'Your prayer request',
    'enterYourName': 'Enter your name',
    'enterYourEmail': 'Enter your email',
    'enterValidEmail': 'Enter a valid email',
    'prayerTooShort':
        'Please share at least a few words (10+ characters)',
    'submitPrayerRequest': 'Submit Prayer Request',
    'prayerSubmitFailed':
        'Could not submit your prayer request. Please try again.',
    'signInToSave': 'Sign in to save chat history across devices.',
    'signIn': 'Sign in',
    'signedInAs': 'Signed in as {name}',
    'signedOut': 'Signed out',
    'translatingReplies': 'Updating replies to the selected language…',
  },
  'es': {
    'home': 'Inicio',
    'store': 'Tienda',
    'events': 'Eventos',
    'nordinsAi': "NORDIN'S AI",
    'chat': 'Chat',
    'media': 'Medios',
    'subscribe': 'Suscribirse',
    'prayerInbox': 'Bandeja de oración',
    'language': 'Idioma',
    'sermons': 'Sermones',
    'chats': 'Chats',
    'sermonLibrary': 'Biblioteca de sermones',
    'sermonLibraryEmpty':
        'Los sermones relevantes aparecerán aquí después de que hagas una pregunta.',
    'lastQuestionSources': 'Fuentes de la última pregunta',
    'previousChats': 'Chats anteriores',
    'newChat': 'Nuevo chat',
    'historyEmptySignedIn':
        'Tus chats guardados aparecerán aquí. Comienza una conversación para crear historial.',
    'historyEmptyGuest':
        'Tu chat más reciente se guarda aquí. Mejora a Premium para historial ilimitado.',
    'historyHintFree':
        'Plan gratuito: solo se conserva tu chat más reciente.',
    'historyHintGuest':
        'Invitado: solo se conserva tu chat más reciente. Inicia sesión y ve a Premium para historial ilimitado.',
    'conversation': 'Conversación',
    'newConversation': 'Nueva conversación',
    'deleteChat': 'Eliminar chat',
    'deleteChatTitle': '¿Eliminar chat?',
    'deleteChatBody':
        '¿Quitar “{title}” de tu historial? Esto no se puede deshacer.',
    'cancel': 'Cancelar',
    'delete': 'Eliminar',
    'chatDeleted': 'Chat eliminado',
    'welcomeTitle': 'Bienvenido al Asistente de IA de Nordin',
    'welcomeBody':
        'Esta herramienta está entrenada con las notas de sermones y recursos del Pastor Don. La IA puede producir información inexacta ocasionalmente. Verifica las ideas con tu Biblia.',
    'howCanIHelp': '¿En qué puedo ayudarte?',
    'listeningHint': 'Escuchando… habla tu pregunta',
    'askWithVoice': 'Preguntar con la voz',
    'stopVoiceInput': 'Detener entrada de voz',
    'backToBottom': 'Volver abajo',
    'sermonSourcesCount': 'Fuentes del sermón ({n})',
    'copyToClipboard': 'Copiar al portapapeles',
    'regenerateResponse': 'Regenerar respuesta',
    'copiedToClipboard': '¡Copiado al portapapeles!',
    'responseCancelled': '_Respuesta cancelada por el usuario._',
    'serverError': 'Error: No se pudo conectar con el servidor.',
    'couldNotOpenSource': 'No se pudo abrir la fuente de "{stem}".',
    'prayerRequestForm': 'Formulario de petición de oración',
    'prayerRequest': 'Petición de oración',
    'prayerReceived': 'Tu petición de oración ha sido recibida.',
    'prayerTeamLifting': 'Nuestro equipo de oración estará orando por ti.',
    'sharePrayerNeed': 'Comparte tu necesidad de oración con nosotros.',
    'submitAnonymously': 'Enviar de forma anónima',
    'name': 'Nombre',
    'email': 'Correo electrónico',
    'phoneOptional': 'Teléfono (opcional)',
    'yourPrayerRequest': 'Tu petición de oración',
    'enterYourName': 'Ingresa tu nombre',
    'enterYourEmail': 'Ingresa tu correo',
    'enterValidEmail': 'Ingresa un correo válido',
    'prayerTooShort':
        'Por favor escribe al menos algunas palabras (10+ caracteres)',
    'submitPrayerRequest': 'Enviar petición de oración',
    'prayerSubmitFailed':
        'No se pudo enviar tu petición de oración. Inténtalo de nuevo.',
    'signInToSave':
        'Inicia sesión para guardar el historial de chat en todos tus dispositivos.',
    'signIn': 'Iniciar sesión',
    'signedInAs': 'Sesión iniciada como {name}',
    'signedOut': 'Sesión cerrada',
    'translatingReplies': 'Actualizando respuestas al idioma seleccionado…',
  },
  'fr': {
    'home': 'Accueil',
    'store': 'Boutique',
    'events': 'Événements',
    'nordinsAi': "NORDIN'S AI",
    'chat': 'Chat',
    'media': 'Médias',
    'subscribe': "S'abonner",
    'prayerInbox': 'Boîte de prière',
    'language': 'Langue',
    'sermons': 'Sermons',
    'chats': 'Discussions',
    'sermonLibrary': 'Bibliothèque de sermons',
    'sermonLibraryEmpty':
        'Les sermons pertinents apparaîtront ici après votre question.',
    'lastQuestionSources': 'Sources de la dernière question',
    'previousChats': 'Discussions précédentes',
    'newChat': 'Nouvelle discussion',
    'historyEmptySignedIn':
        'Vos discussions enregistrées apparaîtront ici. Commencez une conversation pour créer un historique.',
    'historyEmptyGuest':
        'Votre discussion la plus récente est enregistrée ici. Passez à Premium pour un historique illimité.',
    'historyHintFree':
        'Offre gratuite : seule votre discussion la plus récente est conservée.',
    'historyHintGuest':
        'Invité : seule votre discussion la plus récente est conservée. Connectez-vous et passez à Premium pour un historique illimité.',
    'conversation': 'Conversation',
    'newConversation': 'Nouvelle conversation',
    'deleteChat': 'Supprimer la discussion',
    'deleteChatTitle': 'Supprimer la discussion ?',
    'deleteChatBody':
        'Retirer « {title} » de votre historique ? Cette action est irréversible.',
    'cancel': 'Annuler',
    'delete': 'Supprimer',
    'chatDeleted': 'Discussion supprimée',
    'welcomeTitle': "Bienvenue sur l'assistant IA de Nordin",
    'welcomeBody':
        "Cet outil est formé sur les notes de sermon et ressources du pasteur Don. L'IA peut parfois produire des informations inexactes. Vérifiez les insights avec votre Bible.",
    'howCanIHelp': 'Comment puis-je vous aider ?',
    'listeningHint': 'Écoute… posez votre question',
    'askWithVoice': 'Demander à la voix',
    'stopVoiceInput': "Arrêter l'entrée vocale",
    'backToBottom': 'Retour en bas',
    'sermonSourcesCount': 'Sources du sermon ({n})',
    'copyToClipboard': 'Copier dans le presse-papiers',
    'regenerateResponse': 'Régénérer la réponse',
    'copiedToClipboard': 'Copié dans le presse-papiers !',
    'responseCancelled': '_Réponse annulée par l’utilisateur._',
    'serverError': 'Erreur : impossible de se connecter au serveur.',
    'couldNotOpenSource': 'Impossible d’ouvrir la source pour « {stem} ».',
    'prayerRequestForm': 'Formulaire de demande de prière',
    'prayerRequest': 'Demande de prière',
    'prayerReceived': 'Votre demande de prière a été reçue.',
    'prayerTeamLifting': 'Notre équipe de prière va prier pour vous.',
    'sharePrayerNeed': 'Partagez votre besoin de prière avec nous.',
    'submitAnonymously': 'Envoyer anonymement',
    'name': 'Nom',
    'email': 'E-mail',
    'phoneOptional': 'Téléphone (facultatif)',
    'yourPrayerRequest': 'Votre demande de prière',
    'enterYourName': 'Entrez votre nom',
    'enterYourEmail': 'Entrez votre e-mail',
    'enterValidEmail': 'Entrez un e-mail valide',
    'prayerTooShort':
        'Veuillez écrire au moins quelques mots (10+ caractères)',
    'submitPrayerRequest': 'Envoyer la demande de prière',
    'prayerSubmitFailed':
        'Impossible d’envoyer votre demande de prière. Réessayez.',
    'signInToSave':
        'Connectez-vous pour enregistrer l’historique de chat sur tous vos appareils.',
    'signIn': 'Se connecter',
    'signedInAs': 'Connecté en tant que {name}',
    'signedOut': 'Déconnecté',
    'translatingReplies': 'Mise à jour des réponses vers la langue choisie…',
  },
  'pt': {
    'home': 'Início',
    'store': 'Loja',
    'events': 'Eventos',
    'nordinsAi': "NORDIN'S AI",
    'chat': 'Chat',
    'media': 'Mídia',
    'subscribe': 'Assinar',
    'prayerInbox': 'Caixa de oração',
    'language': 'Idioma',
    'sermons': 'Sermões',
    'chats': 'Chats',
    'sermonLibrary': 'Biblioteca de sermões',
    'sermonLibraryEmpty':
        'Sermões relevantes aparecerão aqui depois que você fizer uma pergunta.',
    'lastQuestionSources': 'Fontes da última pergunta',
    'previousChats': 'Chats anteriores',
    'newChat': 'Novo chat',
    'historyEmptySignedIn':
        'Seus chats salvos aparecerão aqui. Comece uma conversa para criar histórico.',
    'historyEmptyGuest':
        'Seu chat mais recente é salvo aqui. Faça upgrade para Premium para histórico ilimitado.',
    'historyHintFree':
        'Plano gratuito: apenas seu chat mais recente é mantido.',
    'historyHintGuest':
        'Convidado: apenas seu chat mais recente é mantido. Entre e vá para Premium para histórico ilimitado.',
    'conversation': 'Conversa',
    'newConversation': 'Nova conversa',
    'deleteChat': 'Excluir chat',
    'deleteChatTitle': 'Excluir chat?',
    'deleteChatBody':
        'Remover “{title}” do seu histórico? Isso não pode ser desfeito.',
    'cancel': 'Cancelar',
    'delete': 'Excluir',
    'chatDeleted': 'Chat excluído',
    'welcomeTitle': 'Bem-vindo ao Assistente de IA da Nordin',
    'welcomeBody':
        'Esta ferramenta é treinada com as anotações de sermão e recursos do Pastor Don. A IA pode ocasionalmente produzir informações imprecisas. Verifique os insights com a sua Bíblia.',
    'howCanIHelp': 'Como posso ajudar você?',
    'listeningHint': 'Ouvindo… fale sua pergunta',
    'askWithVoice': 'Perguntar com a voz',
    'stopVoiceInput': 'Parar entrada de voz',
    'backToBottom': 'Voltar ao final',
    'sermonSourcesCount': 'Fontes do sermão ({n})',
    'copyToClipboard': 'Copiar para a área de transferência',
    'regenerateResponse': 'Regenerar resposta',
    'copiedToClipboard': 'Copiado para a área de transferência!',
    'responseCancelled': '_Resposta cancelada pelo usuário._',
    'serverError': 'Erro: Não foi possível conectar ao servidor.',
    'couldNotOpenSource': 'Não foi possível abrir a fonte de "{stem}".',
    'prayerRequestForm': 'Formulário de pedido de oração',
    'prayerRequest': 'Pedido de oração',
    'prayerReceived': 'Seu pedido de oração foi recebido.',
    'prayerTeamLifting': 'Nossa equipe de oração estará orando por você.',
    'sharePrayerNeed': 'Compartilhe sua necessidade de oração conosco.',
    'submitAnonymously': 'Enviar anonimamente',
    'name': 'Nome',
    'email': 'E-mail',
    'phoneOptional': 'Telefone (opcional)',
    'yourPrayerRequest': 'Seu pedido de oração',
    'enterYourName': 'Digite seu nome',
    'enterYourEmail': 'Digite seu e-mail',
    'enterValidEmail': 'Digite um e-mail válido',
    'prayerTooShort':
        'Por favor, escreva pelo menos algumas palavras (10+ caracteres)',
    'submitPrayerRequest': 'Enviar pedido de oração',
    'prayerSubmitFailed':
        'Não foi possível enviar seu pedido de oração. Tente novamente.',
    'signInToSave':
        'Entre para salvar o histórico de chat em todos os dispositivos.',
    'signIn': 'Entrar',
    'signedInAs': 'Conectado como {name}',
    'signedOut': 'Sessão encerrada',
    'translatingReplies': 'Atualizando respostas para o idioma selecionado…',
  },
  'de': {
    'home': 'Startseite',
    'store': 'Shop',
    'events': 'Veranstaltungen',
    'nordinsAi': "NORDIN'S AI",
    'chat': 'Chat',
    'media': 'Medien',
    'subscribe': 'Abonnieren',
    'prayerInbox': 'Gebets-Posteingang',
    'language': 'Sprache',
    'sermons': 'Predigten',
    'chats': 'Chats',
    'sermonLibrary': 'Predigtbibliothek',
    'sermonLibraryEmpty':
        'Relevante Predigten erscheinen hier, nachdem Sie eine Frage gestellt haben.',
    'lastQuestionSources': 'Quellen der letzten Frage',
    'previousChats': 'Frühere Chats',
    'newChat': 'Neuer Chat',
    'historyEmptySignedIn':
        'Ihre gespeicherten Chats erscheinen hier. Starten Sie ein Gespräch, um Verlauf aufzubauen.',
    'historyEmptyGuest':
        'Ihr neuester Chat wird hier gespeichert. Upgraden Sie auf Premium für unbegrenzten Verlauf.',
    'historyHintFree':
        'Kostenloser Plan: Nur Ihr neuester Chat wird behalten.',
    'historyHintGuest':
        'Gast: Nur Ihr neuester Chat wird behalten. Melden Sie sich an und wechseln Sie zu Premium für unbegrenzten Verlauf.',
    'conversation': 'Unterhaltung',
    'newConversation': 'Neue Unterhaltung',
    'deleteChat': 'Chat löschen',
    'deleteChatTitle': 'Chat löschen?',
    'deleteChatBody':
        '„{title}“ aus Ihrem Verlauf entfernen? Dies kann nicht rückgängig gemacht werden.',
    'cancel': 'Abbrechen',
    'delete': 'Löschen',
    'chatDeleted': 'Chat gelöscht',
    'welcomeTitle': 'Willkommen beim Nordin KI-Assistenten',
    'welcomeBody':
        'Dieses Tool ist auf Predigtnotizen und Ressourcen von Pastor Don trainiert. Die KI kann gelegentlich ungenaue Informationen erzeugen. Bitte prüfen Sie Erkenntnisse anhand Ihrer Bibel.',
    'howCanIHelp': 'Wie kann ich Ihnen helfen?',
    'listeningHint': 'Hört zu… sprechen Sie Ihre Frage',
    'askWithVoice': 'Mit Stimme fragen',
    'stopVoiceInput': 'Spracheingabe stoppen',
    'backToBottom': 'Nach unten',
    'sermonSourcesCount': 'Predigtquellen ({n})',
    'copyToClipboard': 'In Zwischenablage kopieren',
    'regenerateResponse': 'Antwort neu erzeugen',
    'copiedToClipboard': 'In Zwischenablage kopiert!',
    'responseCancelled': '_Antwort vom Benutzer abgebrochen._',
    'serverError': 'Fehler: Verbindung zum Server fehlgeschlagen.',
    'couldNotOpenSource': 'Quelle für „{stem}“ konnte nicht geöffnet werden.',
    'prayerRequestForm': 'Gebetsanliegen-Formular',
    'prayerRequest': 'Gebetsanliegen',
    'prayerReceived': 'Ihr Gebetsanliegen wurde empfangen.',
    'prayerTeamLifting': 'Unser Gebetsteam wird für Sie beten.',
    'sharePrayerNeed': 'Teilen Sie Ihr Gebetsanliegen mit uns.',
    'submitAnonymously': 'Anonym absenden',
    'name': 'Name',
    'email': 'E-Mail',
    'phoneOptional': 'Telefon (optional)',
    'yourPrayerRequest': 'Ihr Gebetsanliegen',
    'enterYourName': 'Geben Sie Ihren Namen ein',
    'enterYourEmail': 'Geben Sie Ihre E-Mail ein',
    'enterValidEmail': 'Geben Sie eine gültige E-Mail ein',
    'prayerTooShort':
        'Bitte schreiben Sie mindestens ein paar Worte (10+ Zeichen)',
    'submitPrayerRequest': 'Gebetsanliegen senden',
    'prayerSubmitFailed':
        'Ihr Gebetsanliegen konnte nicht gesendet werden. Bitte versuchen Sie es erneut.',
    'signInToSave':
        'Melden Sie sich an, um den Chatverlauf geräteübergreifend zu speichern.',
    'signIn': 'Anmelden',
    'signedInAs': 'Angemeldet als {name}',
    'signedOut': 'Abgemeldet',
    'translatingReplies': 'Antworten werden in die gewählte Sprache aktualisiert…',
  },
  'ko': {
    'home': '홈',
    'store': '스토어',
    'events': '행사',
    'nordinsAi': "NORDIN'S AI",
    'chat': '채팅',
    'media': '미디어',
    'subscribe': '구독',
    'prayerInbox': '기도 수신함',
    'language': '언어',
    'sermons': '설교',
    'chats': '채팅',
    'sermonLibrary': '설교 라이브러리',
    'sermonLibraryEmpty': '질문을 하시면 관련 설교가 여기에 표시됩니다.',
    'lastQuestionSources': '최근 질문의 출처',
    'previousChats': '이전 채팅',
    'newChat': '새 채팅',
    'historyEmptySignedIn': '저장된 채팅이 여기에 표시됩니다. 대화를 시작해 기록을 만드세요.',
    'historyEmptyGuest': '가장 최근 채팅만 여기에 저장됩니다. 무제한 기록을 위해 Premium으로 업그레이드하세요.',
    'historyHintFree': '무료 플랜: 가장 최근 채팅만 보관됩니다.',
    'historyHintGuest': '게스트: 가장 최근 채팅만 보관됩니다. 로그인 후 Premium으로 무제한 기록을 이용하세요.',
    'conversation': '대화',
    'newConversation': '새 대화',
    'deleteChat': '채팅 삭제',
    'deleteChatTitle': '채팅을 삭제할까요?',
    'deleteChatBody': '기록에서 “{title}”을(를) 삭제할까요? 이 작업은 되돌릴 수 없습니다.',
    'cancel': '취소',
    'delete': '삭제',
    'chatDeleted': '채팅이 삭제되었습니다',
    'welcomeTitle': "Nordin's AI 어시스턴트에 오신 것을 환영합니다",
    'welcomeBody':
        '이 도구는 Pastor Don의 설교 노트와 자료로 학습되었습니다. AI가 가끔 부정확한 정보를 제공할 수 있으니 성경으로 확인해 주세요.',
    'howCanIHelp': '무엇을 도와드릴까요?',
    'listeningHint': '듣는 중… 질문을 말씀해 주세요',
    'askWithVoice': '음성으로 질문',
    'stopVoiceInput': '음성 입력 중지',
    'backToBottom': '맨 아래로',
    'sermonSourcesCount': '설교 출처 ({n})',
    'copyToClipboard': '클립보드에 복사',
    'regenerateResponse': '응답 다시 생성',
    'copiedToClipboard': '클립보드에 복사되었습니다!',
    'responseCancelled': '_사용자가 응답을 취소했습니다._',
    'serverError': '오류: 서버에 연결할 수 없습니다.',
    'couldNotOpenSource': '"{stem}" 출처를 열 수 없습니다.',
    'prayerRequestForm': '기도 요청 양식',
    'prayerRequest': '기도 요청',
    'prayerReceived': '기도 요청이 접수되었습니다.',
    'prayerTeamLifting': '기도 팀이 당신을 위해 기도하겠습니다.',
    'sharePrayerNeed': '기도가 필요한 내용을 알려 주세요.',
    'submitAnonymously': '익명으로 제출',
    'name': '이름',
    'email': '이메일',
    'phoneOptional': '전화 (선택)',
    'yourPrayerRequest': '기도 요청 내용',
    'enterYourName': '이름을 입력하세요',
    'enterYourEmail': '이메일을 입력하세요',
    'enterValidEmail': '유효한 이메일을 입력하세요',
    'prayerTooShort': '최소 몇 단어 이상 작성해 주세요 (10자 이상)',
    'submitPrayerRequest': '기도 요청 제출',
    'prayerSubmitFailed': '기도 요청을 제출할 수 없습니다. 다시 시도해 주세요.',
    'signInToSave': '기기 간에 채팅 기록을 저장하려면 로그인하세요.',
    'signIn': '로그인',
    'signedInAs': '{name}(으)로 로그인됨',
    'signedOut': '로그아웃됨',
    'translatingReplies': '선택한 언어로 답변을 업데이트하는 중…',
  },
  'zh': {
    'home': '首页',
    'store': '商店',
    'events': '活动',
    'nordinsAi': "NORDIN'S AI",
    'chat': '对话',
    'media': '媒体',
    'subscribe': '订阅',
    'prayerInbox': '代祷收件箱',
    'language': '语言',
    'sermons': '讲道',
    'chats': '对话',
    'sermonLibrary': '讲道资料库',
    'sermonLibraryEmpty': '提问后，相关讲道将显示在这里。',
    'lastQuestionSources': '上一个问题的来源',
    'previousChats': '历史对话',
    'newChat': '新对话',
    'historyEmptySignedIn': '已保存的对话会显示在这里。开始对话以建立历史记录。',
    'historyEmptyGuest': '这里只保存最近一次对话。升级到 Premium 可获得无限历史记录。',
    'historyHintFree': '免费方案：仅保留最近一次对话。',
    'historyHintGuest': '访客：仅保留最近一次对话。登录并升级 Premium 可获得无限历史记录。',
    'conversation': '对话',
    'newConversation': '新对话',
    'deleteChat': '删除对话',
    'deleteChatTitle': '删除对话？',
    'deleteChatBody': '从历史记录中移除“{title}”？此操作无法撤销。',
    'cancel': '取消',
    'delete': '删除',
    'chatDeleted': '对话已删除',
    'welcomeTitle': '欢迎使用 Nordin AI 助手',
    'welcomeBody':
        '本工具基于 Pastor Don 的讲道笔记与资源训练。AI 偶尔可能产生不准确的信息，请用圣经核实见解。',
    'howCanIHelp': '我能为您做什么？',
    'listeningHint': '正在聆听…请说出您的问题',
    'askWithVoice': '语音提问',
    'stopVoiceInput': '停止语音输入',
    'backToBottom': '回到底部',
    'sermonSourcesCount': '讲道来源 ({n})',
    'copyToClipboard': '复制到剪贴板',
    'regenerateResponse': '重新生成回复',
    'copiedToClipboard': '已复制到剪贴板！',
    'responseCancelled': '_用户已取消回复。_',
    'serverError': '错误：无法连接到服务器。',
    'couldNotOpenSource': '无法打开“{stem}”的来源。',
    'prayerRequestForm': '代祷请求表单',
    'prayerRequest': '代祷请求',
    'prayerReceived': '您的代祷请求已收到。',
    'prayerTeamLifting': '我们的代祷团队将为您祷告。',
    'sharePrayerNeed': '请与我们分享您的代祷需要。',
    'submitAnonymously': '匿名提交',
    'name': '姓名',
    'email': '电子邮箱',
    'phoneOptional': '电话（可选）',
    'yourPrayerRequest': '您的代祷请求',
    'enterYourName': '请输入姓名',
    'enterYourEmail': '请输入电子邮箱',
    'enterValidEmail': '请输入有效的电子邮箱',
    'prayerTooShort': '请至少写几个字（10个字符以上）',
    'submitPrayerRequest': '提交代祷请求',
    'prayerSubmitFailed': '无法提交代祷请求，请重试。',
    'signInToSave': '登录后可在多设备间保存聊天记录。',
    'signIn': '登录',
    'signedInAs': '已以 {name} 登录',
    'signedOut': '已退出登录',
    'translatingReplies': '正在将回复更新为所选语言…',
  },
};
