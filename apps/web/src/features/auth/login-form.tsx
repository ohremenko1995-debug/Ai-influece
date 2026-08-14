"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ErrorNotice,
  Field,
  Input,
} from "@influenceros/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { authApi, queryKeys } from "@/lib/api";
import { describeError, requestIdOf } from "@/lib/api-client";
import { useSessionStore } from "@/lib/auth-store";

const schema = z.object({
  email: z.string().min(1, "Email is required").email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});

type FormValues = z.infer<typeof schema>;

export function LoginForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const setTokens = useSessionStore((state) => state.setTokens);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });

  const login = useMutation({
    mutationFn: (values: FormValues) => authApi.login(values.email, values.password),
    onSuccess: async (tokens) => {
      setTokens(tokens);
      // The previous session's cached data must not be visible to the new one.
      await queryClient.invalidateQueries({ queryKey: queryKeys.me });
      router.replace("/dashboard");
    },
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2 pb-1">
          <Sparkles className="text-accent size-5" aria-hidden />
          <CardTitle className="text-base">InfluencerOS</CardTitle>
        </div>
        <CardDescription>Sign in to the production control center.</CardDescription>
      </CardHeader>

      <CardContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={handleSubmit((values) => login.mutate(values))}
          noValidate
        >
          <Field label="Email" htmlFor="email" error={errors.email?.message} required>
            <Input
              type="email"
              autoComplete="username"
              autoFocus
              placeholder="you@example.com"
              {...register("email")}
            />
          </Field>

          <Field label="Password" htmlFor="password" error={errors.password?.message} required>
            <Input type="password" autoComplete="current-password" {...register("password")} />
          </Field>

          {login.error ? (
            <ErrorNotice
              title="Could not sign in"
              message={describeError(login.error)}
              requestId={requestIdOf(login.error)}
            />
          ) : null}

          <Button type="submit" loading={login.isPending} className="w-full">
            Sign in
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
