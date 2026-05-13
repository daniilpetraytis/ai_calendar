import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <div className="flex min-h-[calc(100vh-7rem)] items-center justify-center">
      <SignIn
        path="/sign-in"
        routing="path"
        signUpUrl="/sign-up"
        forceRedirectUrl="/calendar"
      />
    </div>
  );
}
