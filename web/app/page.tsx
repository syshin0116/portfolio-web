import { Suspense } from "react";
import Footer from "@/components/footer";
import { Navbar } from "@/components/navbar";
import ChatSection from "@/components/chat-section";
import { RecentPosts } from "@/components/recent-posts";
import { RecentProjects } from "@/components/recent-projects";

export default function Home() {
  return (
    <>
      <Navbar />
      <Suspense
        fallback={
          <div className="w-full h-[calc(100vh-73px)] flex items-center justify-center">
            Loading...
          </div>
        }
      >
        <ChatSection />
      </Suspense>

      <div className="border-t bg-muted/30">
        <div className="container mx-auto px-4 md:px-6 py-14 grid md:grid-cols-2 gap-12">
          <RecentPosts />
          <RecentProjects />
        </div>
      </div>

      <Footer />
    </>
  );
}
