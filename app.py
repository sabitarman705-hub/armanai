import os, uuid, threading, base64, urllib.request, json, sqlite3
from functools import wraps
import cv2
import numpy as np
import fal_client
import stripe
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.secret_key = os.getenv('SECRET_KEY', 'armanai-secret-2026')

# ── Stripe ────────────────────────────────────────────────────────────────────
stripe.api_key            = os.getenv('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET     = os.getenv('STRIPE_WEBHOOK_SECRET', '')

# ── Google OAuth ───────────────────────────────────────────────────────────────
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

# ── Auth (SQLite) ──────────────────────────────────────────────────────────────
DB_PATH = os.getenv('DB_PATH', os.path.join(os.path.dirname(__file__), 'users.db'))

def _db():
    db = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=NORMAL')
    return db

def _init_db():
    db = _db()
    db.execute('''CREATE TABLE IF NOT EXISTS users (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        username  TEXT    NOT NULL,
        email     TEXT    UNIQUE,
        password  TEXT,
        google_id TEXT    UNIQUE,
        avatar    TEXT,
        balance   REAL    NOT NULL DEFAULT 0.0
    )''')
    for col in ('email TEXT', 'google_id TEXT', 'avatar TEXT', 'balance REAL NOT NULL DEFAULT 0.0'):
        try: db.execute(f'ALTER TABLE users ADD COLUMN {col}')
        except: pass
    db.commit(); db.close()

_init_db()

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return wrapper

FAL_KEY = os.getenv('FAL_KEY', '').strip().lstrip('﻿')
if FAL_KEY:
    os.environ['FAL_KEY'] = FAL_KEY

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# cost = 5сек видеоның нақты бағасы $ (fal.ai биллинг бойынша, аудиосыз)
KLING_FAL_MODELS = {
    'v1-std':      {'id': 'fal-ai/kling-video/v1/standard/image-to-video',       'name': 'Kling v1',     'tag': 'Standard',   'cost': 0.035, 'type': 'kling'},
    'v1-pro':      {'id': 'fal-ai/kling-video/v1/pro/image-to-video',            'name': 'Kling v1',     'tag': 'Pro',        'cost': 0.07,  'type': 'kling'},
    'v1.5-std':    {'id': 'fal-ai/kling-video/v1.5/standard/image-to-video',     'name': 'Kling v1.5',   'tag': 'Standard',   'cost': 0.05,  'type': 'kling'},
    'v1.5-pro':    {'id': 'fal-ai/kling-video/v1.5/pro/image-to-video',          'name': 'Kling v1.5',   'tag': 'Pro ⭐',     'cost': 0.10,  'type': 'kling'},
    'v2.5-turbo':  {'id': 'fal-ai/kling-video/v2.5-turbo/pro/image-to-video',    'name': 'Kling v2.5',   'tag': 'Turbo Pro',  'cost': 0.35,  'type': 'kling'},
    'v2.6-pro':    {'id': 'fal-ai/kling-video/v2.6/pro/image-to-video',          'name': 'Kling v2.6',   'tag': 'Pro 🔥',     'cost': 0.35,  'type': 'kling'},
    'v3-pro':      {'id': 'fal-ai/kling-video/v3/pro/image-to-video',            'name': 'Kling v3',     'tag': 'Pro 💎',     'cost': 0.56,  'type': 'kling'},
    'nano-banana': {'id': 'fal-ai/nano-banana/edit',                             'name': 'Nano Banana',  'tag': 'Edit 🍌',    'cost': 0.03,  'type': 'edit'},
    'seedance':    {'id': 'bytedance/seedance-2.0/image-to-video',               'name': 'Seedance 2.0', 'tag': 'ByteDance',  'cost': 0.10,  'type': 'video'},
}

RESTORE_MODELS = {
    'denoise': 'Тазарту — шуылды жою',
    'sharpen': 'Анықтық — бұлдыр + контраст',
    'upscale': '2× Үлкейту',
    'full':    'Толық өңдеу (ең жақсы)',
}

_DATA_DIR   = os.path.dirname(os.getenv('DB_PATH', os.path.join(os.path.dirname(__file__), 'users.db')))
_TASKS_FILE = os.path.join(_DATA_DIR, 'tasks_cache.json')
_tasks_lock = threading.Lock()

def _load_tasks() -> dict:
    try:
        if os.path.exists(_TASKS_FILE):
            with open(_TASKS_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _persist_tasks():
    try:
        with open(_TASKS_FILE, 'w') as f:
            json.dump(_tasks, f)
    except Exception:
        pass

_tasks: dict = _load_tasks()


# ── Helpers ───────────────────────────────────────────────────────────────────

def save_upload(file):
    ext  = os.path.splitext(secure_filename(file.filename))[1] or '.jpg'
    path = os.path.join(app.config['UPLOAD_FOLDER'], str(uuid.uuid4()) + ext)
    file.save(path)
    return path


def compress_for_api(filepath, max_dim=1024, quality=82):
    img = cv2.imread(filepath)
    if img is None:
        raise Exception('Суретті оқу мүмкін болмады')
    h, w = img.shape[:2]
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        img   = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    b64    = base64.b64encode(buf.tobytes()).decode()
    return f'data:image/jpeg;base64,{b64}'


def _extract_output_url(data: dict) -> str:
    for field in ('video', 'image', 'output'):
        val = data.get(field)
        if isinstance(val, dict):
            return val.get('url', '')
        if isinstance(val, str) and val.startswith('http'):
            return val
    for field in ('videos', 'images'):
        lst = data.get(field)
        if lst and isinstance(lst, list):
            item = lst[0]
            if isinstance(item, dict):
                return item.get('url', '')
            return str(item)
    return ''


def build_model_input(model_info, before_uri, after_uri, prompt, neg_prompt, duration, aspect):
    mtype = model_info.get('type', 'kling')

    if mtype == 'edit':
        return {'image_url': before_uri, 'prompt': prompt}

    if mtype == 'video' and 'seedance' in model_info['id']:
        return {
            'image_url':    before_uri,
            'prompt':       prompt,
            'duration':     int(duration),
            'aspect_ratio': aspect,
        }

    inp = {
        'prompt':          prompt,
        'negative_prompt': neg_prompt,
        'image_url':       before_uri,
        'duration':        int(duration),
        'aspect_ratio':    aspect,
    }
    if after_uri:
        inp['tail_image_url'] = after_uri
    return inp


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect('/')
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = _db()
        user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        db.close()
        if user and user['password'] and check_password_hash(user['password'], password):
            session['user_id']  = user['id']
            session['username'] = user['username']
            session['avatar']   = user['avatar'] or ''
            return redirect('/')
        error = 'Қате логин немесе пароль'
    return render_template('auth.html', mode='login', error=error)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect('/')
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm',  '')
        if len(username) < 3:
            error = 'Аты кем дегенде 3 таңба болуы керек'
        elif len(password) < 6:
            error = 'Пароль кем дегенде 6 таңба болуы керек'
        elif password != confirm:
            error = 'Парольдер сәйкес келмейді'
        else:
            try:
                db = _db()
                db.execute('INSERT INTO users (username, password) VALUES (?,?)',
                           (username, generate_password_hash(password)))
                db.commit()
                user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
                db.close()
                session['user_id']  = user['id']
                session['username'] = user['username']
                session['avatar']   = ''
                return redirect('/')
            except sqlite3.IntegrityError:
                db.close()
                error = 'Бұл атпен аккаунт бар, басқа ат таңда'
    return render_template('auth.html', mode='register', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# ── Google OAuth routes ────────────────────────────────────────────────────────

@app.route('/auth/google')
def auth_google():
    callback = url_for('auth_google_callback', _external=True)
    return google.authorize_redirect(callback)

@app.route('/auth/google/callback')
def auth_google_callback():
    try:
        token     = google.authorize_access_token()
        user_info = token.get('userinfo') or google.userinfo()
    except Exception:
        return redirect('/login?error=google')

    g_id   = user_info.get('sub', '')
    email  = user_info.get('email', '')
    name   = user_info.get('name', email.split('@')[0])
    avatar = user_info.get('picture', '')

    db = _db()
    try:
        user = db.execute('SELECT * FROM users WHERE google_id=?', (g_id,)).fetchone()
        if not user:
            user = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
            if user:
                db.execute('UPDATE users SET google_id=?, avatar=? WHERE id=?',
                           (g_id, avatar, user['id']))
                db.commit()
                user = db.execute('SELECT * FROM users WHERE google_id=?', (g_id,)).fetchone()
            else:
                username = name.replace(' ', '_')[:20] or 'user'
                base, n = username, 1
                while db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone():
                    username = f'{base}{n}'; n += 1
                db.execute(
                    'INSERT INTO users (username, email, google_id, avatar) VALUES (?,?,?,?)',
                    (username, email, g_id, avatar)
                )
                db.commit()
                user = db.execute('SELECT * FROM users WHERE google_id=?', (g_id,)).fetchone()

        uid     = user['id']
        uname   = user['username']
        uavatar = user['avatar'] or ''
    finally:
        db.close()

    session['user_id']  = uid
    session['username'] = uname
    session['avatar']   = uavatar
    return redirect('/')


# ── Balance API ────────────────────────────────────────────────────────────────

@app.route('/api/balance', methods=['GET'])
@login_required
def api_balance_get():
    db   = _db()
    row  = db.execute('SELECT balance FROM users WHERE id=?', (session['user_id'],)).fetchone()
    db.close()
    return jsonify({'balance': round(row['balance'], 4) if row else 0.0})

@app.route('/api/balance', methods=['POST'])
@login_required
def api_balance_set():
    data   = request.get_json(silent=True) or {}
    action = data.get('action', 'deduct')
    amount = float(data.get('amount', 0))
    # Тек admin ғана баланс қоса немесе орната алады
    if action in ('topup', 'set'):
        db = _db()
        user = db.execute('SELECT username FROM users WHERE id=?', (session['user_id'],)).fetchone()
        db.close()
        if not user or user['username'] != 'admin':
            return jsonify({'error': 'Рұқсат жоқ'}), 403
    db = _db()
    try:
        if action == 'deduct':
            db.execute('UPDATE users SET balance = MAX(0, balance - ?) WHERE id=?',
                       (amount, session['user_id']))
        elif action == 'topup':
            db.execute('UPDATE users SET balance = balance + ? WHERE id=?',
                       (amount, session['user_id']))
        else:  # set
            db.execute('UPDATE users SET balance = ? WHERE id=?',
                       (amount, session['user_id']))
        db.commit()
        row = db.execute('SELECT balance FROM users WHERE id=?', (session['user_id'],)).fetchone()
        return jsonify({'balance': round(row['balance'], 4)})
    finally:
        db.close()


@app.route('/api/admin/topup', methods=['POST'])
@login_required
def api_admin_topup():
    """Тек admin пайдаланушының балансын толтыра алады."""
    db   = _db()
    user = db.execute('SELECT username FROM users WHERE id=?', (session['user_id'],)).fetchone()
    db.close()
    if not user or user['username'] != 'admin':
        return jsonify({'error': 'Рұқсат жоқ'}), 403
    data      = request.get_json(silent=True) or {}
    target_id = int(data.get('user_id', 0))
    amount    = float(data.get('amount', 0))
    if amount <= 0 or not target_id:
        return jsonify({'error': 'Қате деректер'}), 400
    db = _db()
    try:
        db.execute('UPDATE users SET balance = balance + ? WHERE id=?', (amount, target_id))
        db.commit()
        row = db.execute('SELECT balance FROM users WHERE id=?', (target_id,)).fetchone()
        return jsonify({'balance': round(row['balance'], 4) if row else 0})
    finally:
        db.close()


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/restore')
@login_required
def restore_page():
    return render_template('restore.html', models=RESTORE_MODELS)

@app.route('/video')
@login_required
def video_page():
    return render_template('video.html', models=KLING_FAL_MODELS)


# ── Photo Enhancement (OpenCV) ────────────────────────────────────────────────

@app.route('/api/restore', methods=['POST'])
@login_required
def api_restore():
    if 'photo' not in request.files:
        return jsonify({'error': 'Сурет жоқ'}), 400
    orig_path = save_upload(request.files['photo'])
    mode      = request.form.get('model', 'full')
    try:
        out = enhance_local(orig_path, mode)
        return jsonify({'success': True,
                        'result':   '/' + out.replace('\\', '/'),
                        'original': '/' + orig_path.replace('\\', '/')})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def enhance_local(filepath, mode):
    img = cv2.imread(filepath)
    if img is None:
        raise Exception('Суретті ашу мүмкін болмады')
    r = img.copy()
    if mode in ('denoise', 'full'):
        r = cv2.fastNlMeansDenoisingColored(r, None, 10, 10, 7, 21)
    if mode in ('sharpen', 'full'):
        blur = cv2.GaussianBlur(r, (0, 0), 3)
        r    = cv2.addWeighted(r, 1.6, blur, -0.6, 0)
        lab  = cv2.cvtColor(r, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l    = cv2.createCLAHE(2.5, (8, 8)).apply(l)
        r    = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    if mode in ('upscale', 'full'):
        h, w = r.shape[:2]
        r    = cv2.resize(r, (w * 2, h * 2), interpolation=cv2.INTER_LANCZOS4)
        kern = np.array([[0, -0.3, 0], [-0.3, 2.2, -0.3], [0, -0.3, 0]])
        r    = cv2.filter2D(r, -1, kern)
    out = os.path.join(app.config['UPLOAD_FOLDER'], str(uuid.uuid4()) + '_enhanced.jpg')
    cv2.imwrite(out, r, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return out


# ── Video Generation (fal_client) ─────────────────────────────────────────────

@app.route('/api/generate-video', methods=['POST'])
@login_required
def api_generate_video():
    if not FAL_KEY:
        return jsonify({'error': '❌ FAL_KEY орнатылмаған (.env файлын тексер)'}), 400
    if 'before_photo' not in request.files:
        return jsonify({'error': 'Кем дегенде бір фото керек'}), 400

    model_key  = request.form.get('model', 'v1.5-pro')
    model_info = KLING_FAL_MODELS.get(model_key, KLING_FAL_MODELS['v1.5-pro'])
    cost       = model_info['cost']

    # Баланс жеткілікті екенін тексеру
    db  = _db()
    row = db.execute('SELECT balance FROM users WHERE id=?', (session['user_id'],)).fetchone()
    db.close()
    balance = row['balance'] if row else 0.0
    if balance < cost:
        return jsonify({'error': f'Баланс жеткіліксіз. Қажет: ${cost:.3f}, бар: ${balance:.4f}'}), 402

    # Балансты алдын ала шегер
    db = _db()
    db.execute('UPDATE users SET balance = balance - ? WHERE id=? AND balance >= ?',
               (cost, session['user_id'], cost))
    db.commit()
    db.close()

    before_path = save_upload(request.files['before_photo'])
    after_file  = request.files.get('after_photo')
    after_path  = save_upload(after_file) if after_file and after_file.filename else None

    duration   = request.form.get('duration', '5')
    prompt     = request.form.get('prompt', 'smooth cinematic transformation')
    neg_prompt = request.form.get('neg_prompt', 'blurry, distorted, low quality, watermark')
    aspect     = request.form.get('aspect_ratio', '16:9')
    model_id   = model_info['id']

    try:
        before_uri = compress_for_api(before_path)
        after_uri  = compress_for_api(after_path) if after_path else None
        inp = build_model_input(model_info, before_uri, after_uri,
                                prompt, neg_prompt, duration, aspect)

        handle  = fal_client.submit(model_id, arguments=inp)
        fal_rid = handle.request_id

        task_id = str(uuid.uuid4())
        with _tasks_lock:
            _tasks[task_id] = {
                'model_id': model_id,
                'fal_rid':  fal_rid,
                'user_id':  session['user_id'],
                'cost':     cost,
            }
            _persist_tasks()

        return jsonify({'success': True, 'task_id': task_id, 'cost': cost})
    except Exception as e:
        # fal.ai қатесі болса балансты қайтар
        db = _db()
        db.execute('UPDATE users SET balance = balance + ? WHERE id=?',
                   (cost, session['user_id']))
        db.commit()
        db.close()
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': f'fal.ai қатесі: {str(e)}'}), 500


@app.route('/api/video-status/<task_id>')
@login_required
def api_video_status(task_id):
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Тапсырма табылмады'}), 404

    model_id = task['model_id']
    fal_rid  = task['fal_rid']

    try:
        status = fal_client.status(model_id, fal_rid, with_logs=False)

        if isinstance(status, fal_client.Completed):
            if status.error:
                db = _db()
                db.execute('UPDATE users SET balance = balance + ? WHERE id=?',
                           (task['cost'], task['user_id']))
                db.commit()
                db.close()
                with _tasks_lock:
                    _tasks.pop(task_id, None)
                    _persist_tasks()
                return jsonify({'status': 'failed', 'video_url': '', 'error_msg': status.error})

            result = fal_client.result(model_id, fal_rid)
            url    = _extract_output_url(result)
            with _tasks_lock:
                _tasks.pop(task_id, None)
                _persist_tasks()
            return jsonify({'status': 'succeed', 'video_url': url})

        if isinstance(status, fal_client.Queued):
            return jsonify({'status': 'processing', 'queue_pos': status.position})

        return jsonify({'status': 'processing', 'video_url': ''})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/cancel-video/<task_id>', methods=['POST'])
@login_required
def api_cancel_video(task_id):
    with _tasks_lock:
        task = _tasks.pop(task_id, None)
        _persist_tasks()
    if not task:
        return jsonify({'success': True})
    try:
        fal_client.cancel(task['model_id'], task['fal_rid'])
    except Exception:
        pass
    return jsonify({'success': True})


@app.route('/api/download-video')
@login_required
def api_download_video():
    url  = request.args.get('url', '')
    name = request.args.get('name', 'file')
    if not url.startswith('https://'):
        return 'Bad URL', 400
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=90) as r:
            data = r.read()
            ct   = r.headers.get('Content-Type', 'application/octet-stream').split(';')[0]
        return Response(data, content_type=ct,
            headers={'Content-Disposition': f'attachment; filename="{name}"'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Stripe төлем роуттары ──────────────────────────────────────────────────────

TOPUP_AMOUNTS = [5, 10, 20, 50]   # USD

@app.route('/topup')
@login_required
def topup_page():
    db  = _db()
    row = db.execute('SELECT balance FROM users WHERE id=?', (session['user_id'],)).fetchone()
    db.close()
    balance = round(row['balance'], 4) if row else 0.0
    return render_template('topup.html', amounts=TOPUP_AMOUNTS, balance=balance,
                           stripe_configured=bool(stripe.api_key))


@app.route('/api/create-checkout', methods=['POST'])
@login_required
def api_create_checkout():
    if not stripe.api_key:
        return jsonify({'error': 'Stripe баптанбаған (STRIPE_SECRET_KEY жоқ)'}), 503

    data       = request.get_json(silent=True) or {}
    amount_usd = float(data.get('amount', 0))
    if amount_usd < 1 or amount_usd > 500:
        return jsonify({'error': 'Сома 1–500$ арасында болуы керек'}), 400

    try:
        checkout = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency':     'usd',
                    'product_data': {'name': f'ArmanAI баланс ${amount_usd:.2f}'},
                    'unit_amount':  int(amount_usd * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('topup_page', _external=True) + '?canceled=1',
            metadata={
                'user_id':    str(session['user_id']),
                'amount_usd': str(amount_usd),
            },
        )
        return jsonify({'url': checkout.url})
    except stripe.StripeError as e:
        return jsonify({'error': str(e.user_message or e)}), 500


@app.route('/payment/success')
@login_required
def payment_success():
    sid = request.args.get('session_id', '')
    credited = 0.0
    if sid and stripe.api_key:
        try:
            sess     = stripe.checkout.Session.retrieve(sid)
            if sess.payment_status == 'paid' and str(sess.metadata.get('user_id')) == str(session['user_id']):
                credited = float(sess.metadata.get('amount_usd', 0))
        except Exception:
            pass
    db  = _db()
    row = db.execute('SELECT balance FROM users WHERE id=?', (session['user_id'],)).fetchone()
    db.close()
    balance = round(row['balance'], 4) if row else 0.0
    return render_template('payment_success.html', credited=credited, balance=balance)


@app.route('/api/stripe-webhook', methods=['POST'])
def stripe_webhook():
    """Stripe осы URL-ге төлем аяқталғанда хабарлайды."""
    payload    = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        return 'Invalid signature', 400

    if event['type'] == 'checkout.session.completed':
        sess = event['data']['object']
        if sess.get('payment_status') == 'paid':
            try:
                uid        = int(sess['metadata']['user_id'])
                amount_usd = float(sess['metadata']['amount_usd'])
                db = _db()
                db.execute('UPDATE users SET balance = balance + ? WHERE id=?', (amount_usd, uid))
                db.commit()
                db.close()
            except Exception as exc:
                print(f'Webhook balance update error: {exc}')

    return '', 200


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = not os.getenv('RAILWAY_ENVIRONMENT')
    print(f'\n✦  ArmanAI → http://localhost:{port}\n')
    app.run(debug=debug, use_reloader=False, host='0.0.0.0', port=port)
