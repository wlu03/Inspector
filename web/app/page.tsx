import Nav from "@/components/Nav";
import Hero from "@/components/Hero";
import ProblemSection from "@/components/ProblemSection";
import HowItWorks from "@/components/HowItWorks";
import SurfaceGrid from "@/components/SurfaceGrid";
import ProofSection from "@/components/ProofSection";
import Footer from "@/components/Footer";

export default function Home() {
  return (
    <>
      <Nav />
      <main>
        <Hero />
        <ProblemSection />
        <HowItWorks />
        <SurfaceGrid />
        <ProofSection />
      </main>
      <Footer />
    </>
  );
}
