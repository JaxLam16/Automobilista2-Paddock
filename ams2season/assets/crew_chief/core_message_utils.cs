using System;
using System.Collections.Generic;
using System.Diagnostics;
using CrewChiefV4.Audio;
namespace CrewChiefV4 { public static partial class Utilities {
        public static List<MessageFragment> WholeAndFractionalMessage(float number, int fractions = 1, bool rounding = true)
        {
            Debug.Assert(fractions > 0 && fractions < 3);
            var message = new List<MessageFragment>();
            var (whole, frac) = Utilities.WholeAndFractionalPart(number, fractions, rounding);

            bool prefixed = false;
            var prefix = "";

            if (fractions == 2)
            {
                if (frac < 10)
                {
                    // makes sure that "3.01" is reported as "3 point zero 1" not "3 point 1"
                    prefixed = true;
                    prefix = "0";
                }
                else if (frac % 10 == 0)
                {
                    // allows "3.10" to be reported as "3 point 1"
                    frac = frac / 10;
                }
            }

            var ideal = $"numbers/{whole}point{prefix}{frac}";
            if (SoundCache.availableSounds.Contains(ideal))
            {
                message.Add(MessageFragment.Text(ideal));
            }
            else
            {
                message.Add(MessageFragment.Integer(whole));
                message.Add(MessageFragment.Text(NumberReader.folderPoint));
                if (prefixed)
                {
                    message.Add(MessageFragment.Integer(0));
                }
                message.Add(MessageFragment.Integer(frac));
            }
            return message;
        }
        public static Tuple<int, int> WholeAndFractionalPart(float realNumber, int fractions = 1, bool rounding = false)
        {
            Debug.Assert(fractions > 0);
            Debug.Assert(!float.IsNaN(realNumber));
            Debug.Assert(!float.IsInfinity(realNumber));

            if (rounding)
            {
                // rounding is disabled by default for historical reasons, where the caller would do it, so is opt-in
                realNumber = (float)(realNumber + 0.5 * Math.Pow(0.1, fractions));
            }

            // adapted from https://stackoverflow.com/questions/53928162
            // this will for sure break down for anything that needs scientific notation
            double whole = Math.Truncate(realNumber);
            double fractional = (realNumber - whole) * Math.Pow(10, fractions);

            return new Tuple<int, int>((int)whole, (int)fractional);
        }
} }
