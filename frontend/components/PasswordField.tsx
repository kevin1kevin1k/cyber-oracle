"use client";

import { ChangeEventHandler } from "react";

type PasswordFieldProps = {
  id: string;
  label: string;
  value: string;
  onChange: ChangeEventHandler<HTMLInputElement>;
  showPassword: boolean;
  onToggleVisibility: () => void;
  minLength?: number;
  required?: boolean;
  autoComplete?: string;
  ariaInvalid?: boolean;
};

export function PasswordField({
  id,
  label,
  value,
  onChange,
  showPassword,
  onToggleVisibility,
  minLength = 8,
  required = true,
  autoComplete,
  ariaInvalid = false,
}: PasswordFieldProps) {
  return (
    <>
      <label htmlFor={id}>{label}</label>
      <div className="password-input-group">
        <input
          id={id}
          type={showPassword ? "text" : "password"}
          value={value}
          onChange={onChange}
          minLength={minLength}
          required={required}
          autoComplete={autoComplete}
          aria-invalid={ariaInvalid}
        />
        <button
          type="button"
          className="password-toggle"
          onClick={onToggleVisibility}
          aria-pressed={showPassword}
          title={showPassword ? `隱藏${label}` : `顯示${label}`}
        >
          {showPassword ? "隱藏密碼" : "顯示密碼"}
        </button>
      </div>
    </>
  );
}
