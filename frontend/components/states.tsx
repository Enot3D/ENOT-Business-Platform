"use client";

import { AlertCircle, LoaderCircle, Search } from "lucide-react";
import { ApiError } from "@/lib/api";

const messages: Record<string, string> = {
  account_exists: "Аккаунт с этой почтой уже существует. Войдите в него.",
  wrong_current_password: "Текущий пароль указан неверно.",
  csrf_failed: "Защита запроса отклонила действие. Обновите страницу и проверьте адрес входа.",
  invalid_credentials: "Не удалось войти. Проверьте логин и пароль.",
  unauthenticated: "Сессия завершилась. Войдите снова.",
  interpretation_active: "Уже выполняется запрос к аналитику. Дождитесь его завершения.",
  incompatible_interpretation: "Интерпретация не соответствует выбранным нишам или выпуску.",
  idempotency_conflict: "Этот запрос уже был использован с другими параметрами.",
  validation_error: "Сервер отклонил параметры запроса.",
};

export function Failure({ error, retry }: { error: unknown; retry?: () => void }) {
  const status = error instanceof ApiError ? error.status : 0;
  const code = error instanceof ApiError ? error.code : "";
  const message = messages[code] ?? ({
    401: "Не удалось подтвердить вход.",
    403: "Действие отклонено сервером.",
    404: "Страница или ресурс недоступны.",
    409: "Сервер обнаружил конфликт параметров.",
    422: "Проверьте введённые параметры.",
    429: "Лимит запросов исчерпан. Попробуйте позже.",
  } as Record<number, string>)[status] ?? "Сервис временно недоступен. Попробуйте ещё раз.";

  return (
    <div className="state state-error" role="alert">
      <AlertCircle size={19} aria-hidden="true" />
      <div><strong>{message}</strong>
        {error instanceof ApiError && error.requestId && <small>ID запроса {error.requestId}</small>}
        {retry && <button className="button compact" type="button" onClick={retry}>Повторить</button>}
      </div>
    </div>
  );
}

export function Loading({ label = "Загрузка данных…" }: { label?: string }) {
  return <div className="state state-loading" role="status"><LoaderCircle className="spinner" size={20} />{label}</div>;
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return <div className="empty"><Search size={24} aria-hidden="true" /><strong>{title}</strong>{children}</div>;
}
