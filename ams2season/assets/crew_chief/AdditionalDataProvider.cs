using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Windows.Forms;

namespace CrewChiefV4
{
    class AdditionalDataProvider
    {

        // TODO: add more undeserving **** to this list as and when they crawl out the woodwork
        // Mostly for wrecking but some notable exceptions - sangalli for thinking it's ok to threaten people, 
        // hance, hotdog and koch for being extraordinarily ignorant and rude, and so on. My app, my rules :)
        public static HashSet<String> additionalData = new HashSet<String>(StringComparer.InvariantCultureIgnoreCase); 
        public static void validate(String str)
        {
            if (str == null)
            {
                return;
            }
            string trimmed = str.Trim();
            if (trimmed.Length > 0 && additionalData.Contains(trimmed))
            {
                throw new ValidationException();
            }
        }
    }

    /**
     * special exception for special players so they can grumble that the app is spamming an exception. I'd call it something
     * more colourful but my usual charm deserts me.
     */
    class ValidationException : Exception
    {
        public ValidationException()
            : base() { }
    }
}
