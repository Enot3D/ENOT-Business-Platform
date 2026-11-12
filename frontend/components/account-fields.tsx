"use client";

import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";

export const passwordHint = "От 12 до 256 символов, минимум одна буква и одна цифра.";

export function passwordIssue(password: string, confirmation: string) {
  const length = Array.from(password).length;
  if (length < 12 || length > 256 || !/\p{L}/u.test(password) || !/\p{Nd}/u.test(password)) {
    return passwordHint;
  }
  return password === confirmation ? "" : "Пароли не совпадают.";
}

export function PasswordField({ label, name, autoComplete }: {
  label: string;
  name: string;
  autoComplete: "current-password" | "new-password";
}) {
  const [visible, setVisible] = useState(false);
  const Icon = visible ? EyeOff : Eye;
  return <div className="password-field">
    <label htmlFor={name}>{label}</label>
    <div>
      <input id={name} name={name} type={visible ? "text" : "password"} autoComplete={autoComplete}
        autoCapitalize="none" spellCheck={false} required />
      <button type="button" className="button" aria-label={visible ? "Скрыть пароль" : "Показать пароль"}
        aria-controls={name} onClick={() => setVisible(!visible)}><Icon size={19} /></button>
    </div>
  </div>;
}
