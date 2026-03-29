"use client";

import * as React from "react";
import { useState, useEffect } from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { FaGithub } from "react-icons/fa";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import ThemeToggle from "@/components/theme-toggle";
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  navigationMenuTriggerStyle,
} from "@/components/ui/navigation-menu";
import { useAuth } from "@/contexts/AuthContext";
import UserMenu from "@/components/auth/UserMenu";
import { useBlogTree } from "@/components/blog/blog-tree-provider";
import { NavSidebar } from "@/components/blog/nav-sidebar";

const NAV_LINKS = [
  { href: "/", label: "Home" },
  { href: "/blog", label: "Blog" },
  { href: "/projects", label: "Projects" },
  { href: "/about", label: "About" },
];

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, loading } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const blogTree = useBlogTree();
  const isBlog = pathname.startsWith("/blog");

  // Close menu on navigation
  useEffect(() => { setMenuOpen(false) }, [pathname]);

  // Lock body scroll when menu open
  useEffect(() => {
    document.body.style.overflow = menuOpen ? "hidden" : "";
    return () => { document.body.style.overflow = "" };
  }, [menuOpen]);

  const handleHomeClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    e.preventDefault();
    if (pathname === "/") {
      router.push("/?reset=true");
    } else {
      router.push("/");
    }
  };

  const openSearch = () => {
    setMenuOpen(false);
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true })
    );
  };

  return (
    <>
      <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-14 w-full max-w-[1440px] items-center gap-2 px-6 lg:px-8">
          {/* Logo */}
          <Link href="/" onClick={handleHomeClick} className="flex items-center gap-2">
            <Image
              src="/logo.png"
              width={32}
              height={32}
              className="max-h-8 w-auto"
              alt="logo"
            />
            <span className="hidden sm:inline text-lg font-semibold tracking-tighter">
              Syshin0116
            </span>
          </Link>

          {/* Desktop: centered nav links */}
          <div className="hidden lg:flex flex-1 justify-center">
            <NavigationMenu>
              <NavigationMenuList>
                {NAV_LINKS.map(({ href, label }) => (
                  <NavigationMenuItem key={href}>
                    <NavigationMenuLink asChild className={navigationMenuTriggerStyle()}>
                      <Link href={href} onClick={href === "/" ? handleHomeClick : undefined}>
                        {label}
                      </Link>
                    </NavigationMenuLink>
                  </NavigationMenuItem>
                ))}
              </NavigationMenuList>
            </NavigationMenu>
          </div>

          {/* Mobile: spacer */}
          <div className="flex-1 lg:hidden" />

          {/* Desktop: right side */}
          <div className="hidden lg:flex items-center gap-2">
            {isBlog && (
              <button
                onClick={openSearch}
                className="flex items-center gap-1 rounded-md border bg-muted px-3 py-1.5 text-sm text-muted-foreground cursor-pointer hover:bg-muted/80 transition-colors select-none"
              >
                <Search className="h-3.5 w-3.5 mr-1" />
                Search
                <kbd className="ml-2 text-xs opacity-60">⌘K</kbd>
              </button>
            )}
            <Button asChild variant="ghost" size="icon">
              <Link href="https://github.com/syshin0116" target="_blank" rel="noopener noreferrer">
                <FaGithub className="h-5 w-5" />
              </Link>
            </Button>
            <ThemeToggle />
            {!loading && (
              user ? (
                <UserMenu />
              ) : (
                <Button
                  asChild
                  size="sm"
                  className="bg-black text-white hover:bg-black/90 dark:bg-black dark:text-white dark:hover:bg-black/90"
                >
                  <Link href="/login">Login</Link>
                </Button>
              )
            )}
          </div>

          {/* Mobile: search (blog) + GitHub */}
          <div className="flex lg:hidden items-center gap-1">
            {isBlog && (
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={openSearch}>
                <Search className="h-4 w-4" />
              </Button>
            )}
            <Button asChild variant="ghost" size="icon" className="h-8 w-8">
              <Link href="https://github.com/syshin0116" target="_blank" rel="noopener noreferrer">
                <FaGithub className="h-4 w-4" />
              </Link>
            </Button>
          </div>

          {/* Mobile: hamburger ↔ X */}
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden h-8 w-8"
            onClick={() => setMenuOpen((o) => !o)}
            aria-label="Menu"
            aria-expanded={menuOpen}
          >
            <div className="relative h-4 w-4">
              <span
                className="absolute left-0 top-0.5 h-[2px] w-4 rounded-full bg-current transition-all duration-300 origin-center"
                style={menuOpen ? { top: "7px", transform: "rotate(45deg)" } : {}}
              />
              <span
                className="absolute left-0 top-[7px] h-[2px] w-4 rounded-full bg-current transition-all duration-300"
                style={menuOpen ? { opacity: 0 } : {}}
              />
              <span
                className="absolute left-0 bottom-0.5 h-[2px] w-4 rounded-full bg-current transition-all duration-300 origin-center"
                style={menuOpen ? { bottom: "7px", transform: "rotate(-45deg)" } : {}}
              />
            </div>
          </Button>
        </div>
      </header>

      {/* Mobile nav overlay */}
      <div
        className="lg:hidden fixed left-0 right-0 bottom-0 flex-col bg-background"
        style={{
          top: "3.5rem",
          zIndex: 40,
          display: menuOpen ? "flex" : "none",
        }}
      >
        {/* Blog search */}
        {isBlog && (
          <button
            onClick={openSearch}
            className="flex items-center gap-2 mx-4 mt-4 px-3 py-2 rounded-md border text-sm text-muted-foreground hover:bg-muted transition-colors"
          >
            <Search className="h-3.5 w-3.5" />
            <span>Search...</span>
            <kbd className="ml-auto text-[10px] border rounded px-1.5 py-0.5 bg-muted">⌘K</kbd>
          </button>
        )}

        {/* Site nav links */}
        <nav className="flex flex-col gap-1 px-4 pt-4">
          {NAV_LINKS.map(({ href, label }) => {
            const isActive =
              href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                onClick={href === "/" ? handleHomeClick : undefined}
                className={`rounded-md px-3 py-2.5 text-base transition-colors ${
                  isActive
                    ? "font-semibold text-foreground bg-accent"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                }`}
              >
                {label}
              </Link>
            );
          })}
        </nav>

        {/* Blog nav tree (only on blog pages) */}
        {isBlog && blogTree.length > 0 && (
          <>
            <Separator className="mx-4 mt-3" />
            <div className="flex-1 overflow-y-auto px-4 py-3">
              <NavSidebar tree={blogTree} />
            </div>
          </>
        )}

        {/* Spacer when no blog tree */}
        {!isBlog && <div className="flex-1" />}

        {/* Footer */}
        <Separator />
        <div className="flex items-center justify-between px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <div>
            {!loading && (
              user ? (
                <div className="flex items-center gap-2">
                  <UserMenu />
                  <span className="text-sm text-muted-foreground">
                    {user.user_metadata?.full_name || user.user_metadata?.name || user.email?.split("@")[0]}
                  </span>
                </div>
              ) : (
                <Button
                  asChild
                  size="sm"
                  className="bg-black text-white hover:bg-black/90 dark:bg-black dark:text-white dark:hover:bg-black/90"
                >
                  <Link href="/login">Login</Link>
                </Button>
              )
            )}
          </div>
          <div className="flex items-center gap-1">
            <Button asChild variant="ghost" size="icon" className="h-8 w-8">
              <Link href="https://github.com/syshin0116" target="_blank" rel="noopener noreferrer">
                <FaGithub className="h-4 w-4" />
              </Link>
            </Button>
            <ThemeToggle />
          </div>
        </div>
      </div>
    </>
  );
}
