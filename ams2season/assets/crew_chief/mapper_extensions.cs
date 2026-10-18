using System;
using System.Collections.Generic;
namespace CrewChiefV4 { public static class MapperExtensions {
        public static int IndexOfMin<T>(this IEnumerable<T> source, IComparer<T> comparer = null)
        {
            if (source == null)
                throw new ArgumentNullException("source");

            if (comparer == null)
                comparer = Comparer<T>.Default;

            using (var enumerator = source.GetEnumerator())
            {
                if (!enumerator.MoveNext())
                    return -1;    // or maybe throw InvalidOperationException

                int minIndex = 0;
                T minValue = enumerator.Current;

                int index = 0;
                while (enumerator.MoveNext())
                {
                    index++;
                    if (comparer.Compare(enumerator.Current, minValue) < 0)
                    {
                        minIndex = index;
                        minValue = enumerator.Current;
                    }
                }
                return minIndex;
            }
        }
} }
