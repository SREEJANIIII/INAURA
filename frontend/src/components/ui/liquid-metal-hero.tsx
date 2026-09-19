"use client";

import { LiquidMetal, liquidMetalPresets } from '@paper-design/shaders-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { useRef, type ReactNode } from 'react';
import { MotionConfig, motion, useReducedMotionConfig, useScroll, useTransform } from 'framer-motion';

interface LiquidMetalHeroProps {
  badge?: string;
  title: ReactNode;
  subtitle: string;
  primaryCtaLabel: string;
  secondaryCtaLabel?: string;
  onPrimaryCtaClick: () => void;
  onSecondaryCtaClick?: () => void;
  features?: string[];
  /** Shown under the buttons in place of the feature strip, e.g. a small product preview */
  preview?: ReactNode;
  /** "fixed" (default): the metal fills the screen behind the whole page.
      "section": it fills only this hero and pauses once scrolled out of view. */
  background?: "fixed" | "section";
}

export default function LiquidMetalHero({
  badge,
  title,
  subtitle,
  primaryCtaLabel,
  secondaryCtaLabel,
  onPrimaryCtaClick,
  onSecondaryCtaClick,
  features = [],
  preview,
  background = "fixed",
}: LiquidMetalHeroProps) {
  // Respect the device's "reduce motion" setting: still metal, no entrance animations
  const reduceMotion = !!useReducedMotionConfig();
  const metal = liquidMetalPresets[2].params;

  // Scrolling away: the panel sinks back and fades while the metal drifts slower (parallax)
  const sectionRef = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: sectionRef, offset: ["start start", "end start"] });
  const panelScale = useTransform(scrollYProgress, [0, 1], [1, 0.84]);
  const panelY = useTransform(scrollYProgress, [0, 1], [0, 80]);
  const panelOpacity = useTransform(scrollYProgress, [0, 0.75, 1], [1, 0, 0]);
  const metalY = useTransform(scrollYProgress, [0, 1], ["0%", "28%"]);
  const scrollAway = !reduceMotion && background === "section";

  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        delayChildren: 0.2,
        staggerChildren: 0.15
      }
    }
  };

  const itemVariants = {
    hidden: { opacity: 0, y: 30 },
    visible: { opacity: 1, y: 0 }
  };

  const buttonVariants = {
    hidden: { opacity: 0, scale: 0.9 },
    visible: { opacity: 1, scale: 1 }
  };

  return (
    <MotionConfig reducedMotion="user">
    <section ref={sectionRef} className="relative min-h-screen flex items-center justify-center overflow-hidden pt-24 pb-12 sm:pt-28 sm:pb-20">
      <motion.div
        style={{ position: background === "fixed" ? "fixed" : "absolute", inset: 0, zIndex: -10, y: scrollAway ? metalY : 0 }}
      >
        {/* .params: a preset is { name, params }, and LiquidMetal takes the params as its props */}
        <LiquidMetal
          {...metal}
          speed={reduceMotion ? 0 : metal.speed}
          style={{ position: "absolute", inset: 0 }}
        />
      </motion.div>

      <motion.div
        className="container mx-auto px-6 lg:px-8 max-w-7xl"
        style={scrollAway ? { scale: panelScale, y: panelY, opacity: panelOpacity } : undefined}
      >
        {/* Frosted glass panel: keeps the text readable over the dark swirls of the metal */}
        <motion.div
          className="text-center space-y-8 rounded-[2rem] border border-white/60 bg-white/45 px-5 py-10 sm:px-12 sm:py-14 shadow-[inset_0_1px_0_rgba(255,255,255,0.8),0_30px_80px_-30px_rgba(20,20,40,0.5)] backdrop-blur-xl"
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          transition={{ duration: 0.8, ease: [0.25, 0.1, 0.25, 1] }}
        >
          {badge && (
            <motion.div
              className="flex justify-center"
              variants={itemVariants}
            >
              <Badge
                variant="secondary"
                className="bg-foreground/10 text-foreground border-foreground/20 hover:bg-foreground/20 transition-colors duration-300 backdrop-blur-sm"
              >
                {badge}
              </Badge>
            </motion.div>
          )}

          <motion.div
            className="space-y-6"
            variants={itemVariants}
          >
            <motion.h1
              role="heading"
              aria-level={1}
              className="text-5xl sm:text-6xl lg:text-7xl font-bold text-foreground leading-tight tracking-tight"
              variants={itemVariants}
            >
              {title}
            </motion.h1>

            <motion.p
              className="max-w-3xl mx-auto text-xl sm:text-2xl text-foreground/90 leading-relaxed"
              variants={itemVariants}
            >
              {subtitle}
            </motion.p>
          </motion.div>

          <motion.div
            className="flex flex-col sm:flex-row gap-4 justify-center items-center"
            variants={buttonVariants}
          >
            <motion.div
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
            >
              <Button
                onClick={onPrimaryCtaClick}
                size="lg"
                className="rounded-full bg-foreground text-background hover:bg-foreground/90 transition-all duration-300 shadow-2xl text-lg px-8 py-6 font-semibold"
              >
                {primaryCtaLabel}
              </Button>
            </motion.div>

            {secondaryCtaLabel && onSecondaryCtaClick && (
              <motion.div
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
              >
                <Button
                  onClick={onSecondaryCtaClick}
                  variant="outline"
                  size="lg"
                  className="rounded-full border-foreground/30 bg-white/50 text-foreground hover:bg-white/70 hover:border-foreground/50 transition-all duration-300 backdrop-blur-sm text-lg px-8 py-6 font-semibold"
                >
                  {secondaryCtaLabel}
                </Button>
              </motion.div>
            )}
          </motion.div>

          {preview ? (
            <motion.div className="pt-6 sm:pt-8" variants={itemVariants}>
              {preview}
            </motion.div>
          ) : features.length > 0 && (
            <motion.div
              className="pt-12"
              variants={itemVariants}
            >
              <motion.div
                whileHover={{ y: -4 }}
                transition={{ duration: 0.3 }}
              >
                <Card className="rounded-2xl bg-white/50 border-white/70 backdrop-blur-md shadow-lg">
                  <div className="p-6 sm:p-8">
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                      {features.map((feature, index) => (
                        <motion.div
                          key={index}
                          className="flex items-center justify-center text-center"
                          initial={{ opacity: 0, x: -20 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ duration: 0.6, delay: 0.8 + (index * 0.1) }}
                        >
                          <p className="text-foreground/90 font-medium text-lg">
                            {feature}
                          </p>
                        </motion.div>
                      ))}
                    </div>
                  </div>
                </Card>
              </motion.div>
            </motion.div>
          )}
        </motion.div>
      </motion.div>
    </section>
    </MotionConfig>
  );
}
