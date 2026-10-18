using CrewChiefV4.GameState;

namespace CrewChiefV4.Events
{
	internal class TyrePerformanceContainer
	{
		public TyreType type1;

		public TyreType type2;

		public float bestLapDelta;

		public TyrePerformanceContainer(TyreType type1, TyreType type2, float bestLapDelta)
		{
			this.type1 = type1;
			this.type2 = type2;
			this.bestLapDelta = bestLapDelta;
		}
	}
}
