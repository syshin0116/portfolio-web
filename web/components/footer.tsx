import { GithubIcon } from "lucide-react";
import Link from "next/link";
import { Separator } from "@/components/ui/separator";

const Footer = () => {
  return (
    <footer className="border-t bg-muted/30">
      <div className="container mx-auto px-4 md:px-6 py-10">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex flex-col items-center sm:items-start gap-1">
            <span className="text-sm font-medium">Syshin0116</span>
            <span className="text-xs text-muted-foreground">
              AI Engineer @ BrainCrew
            </span>
          </div>

          <nav className="flex items-center gap-6 text-sm text-muted-foreground">
            <Link href="/" className="hover:text-foreground transition-colors">
              Home
            </Link>
            <Link href="/blog" className="hover:text-foreground transition-colors">
              Blog
            </Link>
            <Link href="/projects" className="hover:text-foreground transition-colors">
              Projects
            </Link>
            <Link href="/about" className="hover:text-foreground transition-colors">
              About
            </Link>
          </nav>

          <div className="flex items-center gap-3 text-muted-foreground">
            <Link
              href="https://github.com/syshin0116"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-foreground transition-colors"
            >
              <GithubIcon className="h-5 w-5" />
            </Link>
          </div>
        </div>

        <Separator className="my-6" />

        <p className="text-center text-xs text-muted-foreground">
          &copy; {new Date().getFullYear()} Syshin0116. All rights reserved.
        </p>
      </div>
    </footer>
  );
};

export default Footer;
