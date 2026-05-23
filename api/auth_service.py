from functools import lru_cache

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError
from werkzeug.security import check_password_hash, generate_password_hash

from config import AUTH_COLLECTION_NAME, MONGO_DB_NAME, MONGO_URI

MAX_ACCOUNTS_PER_JETSON = 2


class AuthConfigurationError(RuntimeError):
    pass


def _normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def _normalize_jetson_id(jetson_id: str) -> str:
    return str(jetson_id or "").strip()


@lru_cache(maxsize=1)
def _get_accounts_collection():
    if not MONGO_URI:
        raise AuthConfigurationError("Chua cau hinh MONGO_URI trong bien moi truong.")

    client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=5000,
    )
    client.admin.command("ping")
    collection = client[MONGO_DB_NAME][AUTH_COLLECTION_NAME]
    collection.create_index("email", unique=True)
    return collection


def verify_user_credentials(email: str, password: str):
    normalized_email = _normalize_email(email)
    raw_password = str(password or "")

    if not normalized_email or not raw_password:
        return {
            "ok": False,
            "status": 400,
            "message": "Vui lòng nhập email và mật khẩu.",
        }

    try:
        account = _get_accounts_collection().find_one(
            {"email": normalized_email},
            {"_id": 0, "email": 1, "mat_khau_hash": 1, "jetson_id": 1},
        )
    except AuthConfigurationError as error:
        return {
            "ok": False,
            "status": 500,
            "message": str(error),
        }
    except PyMongoError:
        return {
            "ok": False,
            "status": 503,
            "message": "Không thể kết nối",
        }

    if not account:
        return {
            "ok": False,
            "status": 401,
            "message": "Email hoặc mật khẩu không đúng.",
        }

    password_hash = str(account.get("mat_khau_hash") or "").strip()
    if not password_hash or not check_password_hash(password_hash, raw_password):
        return {
            "ok": False,
            "status": 401,
            "message": "Email hoặc mật khẩu không đúng.",
        }

    return {
        "ok": True,
        "status": 200,
        "email": normalized_email,
        "jetson_id": str(account.get("jetson_id") or "").strip(),
    }


def change_user_password(email: str, current_password: str, new_password: str):
    normalized_email = _normalize_email(email)
    raw_current_password = str(current_password or "")
    raw_new_password = str(new_password or "")

    if not normalized_email or not raw_current_password or not raw_new_password:
        return {
            "ok": False,
            "status": 400,
            "message": "Vui lòng nhập đầy đủ",
        }

    if len(raw_new_password) < 6:
        return {
            "ok": False,
            "status": 400,
            "message": "Mật khẩu mới phải có ít nhất 6 ký tự.",
        }

    try:
        collection = _get_accounts_collection()
        account = collection.find_one(
            {"email": normalized_email},
            {"_id": 1, "mat_khau_hash": 1},
        )
    except AuthConfigurationError as error:
        return {
            "ok": False,
            "status": 500,
            "message": str(error),
        }
    except PyMongoError:
        return {
            "ok": False,
            "status": 503,
            "message": "Khong the ket noi MongoDB Atlas luc nay.",
        }

    if not account:
        return {
            "ok": False,
            "status": 404,
            "message": "không tìm thấy tài khoản với email đã cung cấp.",
        }

    password_hash = str(account.get("mat_khau_hash") or "").strip()
    if not password_hash or not check_password_hash(password_hash, raw_current_password):
        return {
            "ok": False,
            "status": 401,
            "message": "Mật khẩu hiện tại không đúng.",
        }

    if check_password_hash(password_hash, raw_new_password):
        return {
            "ok": False,
            "status": 400,
            "message": "Mật khẩu mới không được trùng với mật khẩu hiện tại.",
        }

    try:
        collection.update_one(
            {"_id": account["_id"]},
            {"$set": {"mat_khau_hash": generate_password_hash(raw_new_password)}},
        )
    except PyMongoError:
        return {
            "ok": False,
            "status": 503,
            "message": "không thể cập nhập",
        }

    return {
        "ok": True,
        "status": 200,
        "message": "Đổi mật khẩu thành công.",
    }


def register_user_account(email: str, password: str, jetson_id: str):
    normalized_email = _normalize_email(email)
    raw_password = str(password or "")
    normalized_jetson_id = _normalize_jetson_id(jetson_id)

    if not normalized_email or not raw_password or not normalized_jetson_id:
        return {
            "ok": False,
            "status": 400,
            "message": "Vui lòng nhập đầy đủ email, mật khẩu và mã thiết bị.",
        }

    if len(raw_password) < 6:
        return {
            "ok": False,
            "status": 400,
            "message": "Mật khẩu phải có ít nhất 6 ký tự.",
        }

    try:
        collection = _get_accounts_collection()
        existing_account = collection.find_one({"email": normalized_email}, {"_id": 1})
        if existing_account:
            return {
                "ok": False,
                "status": 409,
                "message": "Email này đã tồn tại. Vui lòng dùng email khác.",
            }

        jetson_account_count = collection.count_documents({"jetson_id": normalized_jetson_id})
        if jetson_account_count >= MAX_ACCOUNTS_PER_JETSON:
            return {
                "ok": False,
                "status": 409,
                "message": f"Đạt giới hạn tài khoản mã {normalized_jetson_id}.",
            }

        collection.insert_one({
            "email": normalized_email,
            "mat_khau_hash": generate_password_hash(raw_password),
            "jetson_id": normalized_jetson_id,
        })
    except DuplicateKeyError:
        return {
            "ok": False,
            "status": 409,
            "message": "Email này đã tồn tại. Vui lòng dùng email khác.",
        }
    except AuthConfigurationError as error:
        return {
            "ok": False,
            "status": 500,
            "message": str(error),
        }
    except PyMongoError:
        return {
            "ok": False,
            "status": 503,
            "message": "không thể kết nối Data base lúc này.",
        }

    return {
        "ok": True,
        "status": 201,
        "email": normalized_email,
        "jetson_id": normalized_jetson_id,
    }
