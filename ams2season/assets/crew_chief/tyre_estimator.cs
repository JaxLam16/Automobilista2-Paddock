using System;using MathNet.Numerics;
namespace CrewChiefV4 { public static partial class Utilities {
public static double getYEstimate(double[] x_data, double[] y_data, double x_point, int order)
		{
			double[] array = Fit.Polynomial(x_data, y_data, order);
			double num = 0.0;
			for (int i = 0; i < array.Length; i++)
			{
				switch (i)
				{
				case 0:
					num += array[i];
					break;
				case 1:
					num += array[i] * x_point;
					break;
				default:
					num += array[i] * Math.Pow(x_point, i);
					break;
				}
			}
			return num;
		}
} }
