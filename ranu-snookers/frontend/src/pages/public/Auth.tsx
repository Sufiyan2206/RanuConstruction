import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useAuth } from "@/stores/auth";
import { Button, Card, ErrorBox, Field, Input, Tabs } from "@/components/ui";

const loginSchema = z.object({ identifier: z.string().min(2, "Required"), password: z.string().min(1, "Required") });
const pinSchema = z.object({ username: z.string().min(2, "Required"), pin: z.string().regex(/^\d{4,8}$/, "4–8 digits") });
const registerSchema = z.object({
  name: z.string().min(2, "Required"), phone: z.string().regex(/^\+?[0-9 ]{10,15}$/, "Valid mobile number"),
  email: z.union([z.literal(""), z.string().email()]).optional(), password: z.string().min(8, "At least 8 characters"),
});

export function Login() {
  const { login, pinLogin } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [mode, setMode] = useState<"password" | "pin">("password");
  const [error, setError] = useState<unknown>(null);
  const f1 = useForm<z.infer<typeof loginSchema>>({ resolver: zodResolver(loginSchema) });
  const f2 = useForm<z.infer<typeof pinSchema>>({ resolver: zodResolver(pinSchema) });
  const go = (staff: boolean) => nav(params.get("next") ?? (staff ? "/admin" : "/my/bookings"), { replace: true });

  return (
    <div className="mx-auto max-w-md px-4 py-16">
      <Card className="space-y-5">
        <h1 className="text-2xl font-semibold">Sign in</h1>
        <Tabs value={mode} onChange={setMode} items={[{ value: "password", label: "Password" }, { value: "pin", label: "Staff PIN" }]} />
        {mode === "password" ? (
          <form className="space-y-4" onSubmit={f1.handleSubmit(async (v) => {
            setError(null);
            try { const me = await login(v.identifier, v.password); go(me.permissions.some((p) => p !== "self.bookings")); } catch (e) { setError(e); }
          })}>
            <Field label="Username, email or mobile" error={f1.formState.errors.identifier?.message}><Input autoComplete="username" {...f1.register("identifier")} /></Field>
            <Field label="Password" error={f1.formState.errors.password?.message}><Input type="password" autoComplete="current-password" {...f1.register("password")} /></Field>
            <ErrorBox error={error} />
            <Button type="submit" size="lg" className="w-full" loading={f1.formState.isSubmitting}>Sign in</Button>
          </form>
        ) : (
          <form className="space-y-4" onSubmit={f2.handleSubmit(async (v) => {
            setError(null);
            try { await pinLogin(v.username, v.pin); go(true); } catch (e) { setError(e); }
          })}>
            <Field label="Staff username" error={f2.formState.errors.username?.message}><Input autoComplete="username" {...f2.register("username")} /></Field>
            <Field label="PIN" error={f2.formState.errors.pin?.message}><Input type="password" inputMode="numeric" maxLength={8} {...f2.register("pin")} /></Field>
            <ErrorBox error={error} />
            <Button type="submit" size="lg" className="w-full" loading={f2.formState.isSubmitting}>Unlock counter</Button>
          </form>
        )}
        <p className="text-center text-sm text-ink-400">New customer? <Link to="/register" className="text-brass-400 underline">Create an account</Link></p>
      </Card>
    </div>
  );
}

export function Register() {
  const { register: signUp } = useAuth();
  const nav = useNavigate();
  const [error, setError] = useState<unknown>(null);
  const f = useForm<z.infer<typeof registerSchema>>({ resolver: zodResolver(registerSchema) });
  return (
    <div className="mx-auto max-w-md px-4 py-16">
      <Card>
        <h1 className="mb-5 text-2xl font-semibold">Create your RANU account</h1>
        <form className="space-y-4" onSubmit={f.handleSubmit(async (v) => {
          setError(null);
          try { await signUp({ ...v, email: v.email || undefined }); nav("/my/bookings"); } catch (e) { setError(e); }
        })}>
          <Field label="Name" error={f.formState.errors.name?.message}><Input autoComplete="name" {...f.register("name")} /></Field>
          <Field label="Mobile (WhatsApp)" error={f.formState.errors.phone?.message}><Input inputMode="tel" {...f.register("phone")} /></Field>
          <Field label="Email (optional)" error={f.formState.errors.email?.message}><Input type="email" {...f.register("email")} /></Field>
          <Field label="Password" error={f.formState.errors.password?.message}><Input type="password" autoComplete="new-password" {...f.register("password")} /></Field>
          <ErrorBox error={error} />
          <Button type="submit" size="lg" className="w-full" loading={f.formState.isSubmitting}>Create account</Button>
        </form>
      </Card>
    </div>
  );
}
