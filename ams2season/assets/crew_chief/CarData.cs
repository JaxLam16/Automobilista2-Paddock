using CrewChiefV4.Events;
using CrewChiefV4.GameState;
using CrewChiefV4.PCars;

using Newtonsoft.Json;
using Newtonsoft.Json.Converters;

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace CrewChiefV4
{
    public class CarData
    {
        // some temperatures - maybe externalise these
        // These are the peaks. If the tyre exceeds these temps even for one tick over a lap, we'll warn about it. This is why they look so high
        private const float maxColdRoadTyreTempPeak = 40;
        private const float maxWarmRoadTyreTempPeak = 90;
        private const float maxHotRoadTyreTempPeak = 110;

        // very wide range for unknown tyres
        private const float maxColdUnknownRaceTyreTempPeak = 60;
        private const float maxWarmUnknownRaceTyreTempPeak = 117;
        private const float maxHotUnknownRaceTyreTempPeak = 137;

        private const float maxColdHardTyreTempPeak = 78;
        private const float maxWarmHardTyreTempPeak = 110;
        private const float maxHotHardTyreTempPeak = 124;

        private const float maxColdMediumTyreTempPeak = 75;
        private const float maxWarmMediumTyreTempPeak = 105;
        private const float maxHotMediumTyreTempPeak = 120;

        private const float maxColdSoftTyreTempPeak = 70;
        private const float maxWarmSoftTyreTempPeak = 100;
        private const float maxHotSoftTyreTempPeak = 115;

        private const float maxColdSuperSoftTyreTempPeak = 68;
        private const float maxWarmSuperSoftTyreTempPeak = 98;
        private const float maxHotSuperSoftTyreTempPeak = 110;

        private const float maxColdUltraSoftTyreTempPeak = 65;
        private const float maxWarmUltraSoftTyreTempPeak = 95;
        private const float maxHotUltraSoftTyreTempPeak = 107;

        private const float maxColdHyperSoftTyreTempPeak = 60;
        private const float maxWarmHyperSoftTyreTempPeak = 94;
        private const float maxHotHyperSoftTyreTempPeak = 105;

        private const float maxColdWetTyreTempPeak = 40;
        private const float maxWarmWetTyreTempPeak = 80;
        private const float maxHotWetTyreTempPeak = 105;

        private const float maxColdIntermediateTyreTempPeak = 60;
        private const float maxWarmIntermediateTyreTempPeak = 95;
        private const float maxHotIntermediateTyreTempPeak = 110;

        // no idea about these - use similar thresholds to inters?
        private const float maxColdAllTerrainTyreTempPeak = 50;
        private const float maxWarmAllTerrainTyreTempPeak = 95;
        private const float maxHotAllTerrainTyreTempPeak = 110;

        // no idea what range to use here, so use a massive ranges
        private const float maxColdIceTyreTempPeak = -100;
        private const float maxWarmIceTyreTempPeak = 200;
        private const float maxHotIceTyreTempPeak = 300;

        private const float maxColdSnowTyreTempPeak = -100;
        private const float maxWarmSnowTyreTempPeak = 200;
        private const float maxHotSnowTyreTempPeak = 300;
        //

        private const float maxColdBiasPlyTyreTempPeak = 64;
        private const float maxWarmBiasPlyTyreTempPeak = 103;
        private const float maxHotBiasPlyTyreTempPeak = 123;

        // special cases for RaceRoom tyres on different tire model models
        // - the game sends the core temp, not the surface temp

        // model circa 2016:
        private const float maxColdR3E2016PrimeTyreTempPeak = 88;
        private const float maxWarmR3E2016PrimeTyreTempPeak = 105;
        private const float maxHotR3E2016PrimeTyreTempPeak = 110;

        private const float maxColdR3E2016OptionTyreTempPeak = 75;
        private const float maxWarmR3E2016OptionTyreTempPeak = 110;
        private const float maxHotR3E2016OptionTyreTempPeak = 120;

        private const float maxColdR3E2016SoftTyreTempPeak = 85;
        private const float maxWarmR3E2016SoftTyreTempPeak = 100;
        private const float maxHotR3E2016SoftTyreTempPeak = 103;

        private const float maxColdR3E2016MediumTyreTempPeak = 90;
        private const float maxWarmR3E2016MediumTyreTempPeak = 104;
        private const float maxHotR3E2016MediumTyreTempPeak = 108;

        private const float maxColdR3E2016HardTyreTempPeak = 95;
        private const float maxWarmR3E2016HardTyreTempPeak = 108;
        private const float maxHotR3E2016HardTyreTempPeak = 113;

        // model late 2017:
        private const float maxColdR3E2017SoftTyreTempPeak = 60;
        private const float maxWarmR3E2017SoftTyreTempPeak = 94;
        private const float maxHotR3E2017SoftTyreTempPeak = 106;

        private const float maxColdR3E2017MediumTyreTempPeak = 67;
        private const float maxWarmR3E2017MediumTyreTempPeak = 99;
        private const float maxHotR3E2017MediumTyreTempPeak = 110;

        private const float maxColdR3E2017HardTyreTempPeak = 72;
        private const float maxWarmR3E2017HardTyreTempPeak = 100;
        private const float maxHotR3E2017HardTyreTempPeak = 115;

        // special case for F-Junior, maybe need to add this to NSU as well
        private const float maxColdR3E2017F5TyreTempPeak = 50;
        private const float maxWarmR3E2017F5TyreTempPeak = 65;
        private const float maxHotR3E2017F5TyreTempPeak = 80;

        private const float maxColdIronRoadBrakeTemp = 80;
        private const float maxWarmIronRoadBrakeTemp = 500;
        private const float maxHotIronRoadBrakeTemp = 780;

        private const float maxColdIronRaceBrakeTemp = 150;
        private const float maxWarmIronRaceBrakeTemp = 800;
        private const float maxHotIronRaceBrakeTemp = 1000;

        private const float maxColdCeramicBrakeTemp = 150;
        private const float maxWarmCeramicBrakeTemp = 950;
        private const float maxHotCeramicBrakeTemp = 1200;

        private const float maxColdCarbonBrakeTemp = 400;
        private const float maxWarmCarbonBrakeTemp = 1200;
        private const float maxHotCarbonBrakeTemp = 1500;

        // some ACC tyre pressure ranges
        public const float accDryVeryHighPressureThreshold = 28.8f * 6.894f;
        public const float accWetVeryHighPressureThreshold = 33.0f * 6.894f;
        public const float accDryHighPressureThreshold = 28.3f * 6.894f;
        public const float accWetHighPressureThreshold = 32.0f * 6.894f;
        public const float accDryLowPressureThreshold = 27.2f * 6.894f;
        public const float accWetLowPressureThreshold = 29.0f * 6.894f;
        public const float accDryVeryLowPressureThreshold = 26.0f * 6.894f;
        public const float accWetVeryLowPressureThreshold = 27.5f * 6.894f;

        // The ones that don't appear to be used are used for carClassData.json which ends up loaded into CAR_CLASSES
        public enum CarClassEnum
        {
            ALPINE,
            ALPINE_A110_CUP,
            ARCA,
            ARC_CAMERO,
            AUDI_TT_CUP,
            AUDI_TT_VLN,
            BMW_235I,
            BMW_DRIFT_CLASS,
            BMW_M2_CUP,
            BOXER_CUP,
            CAN_AM,
            CARRERA_CUP,
            CATERHAM_620R,
            CATERHAM_ACADEMY,
            CATERHAM_SUPERLIGHT,
            CATERHAM_SUPERSPORT,
            CAYMAN_CLUBSPORT,
            CLIO_CUP,
            COPA_CLASSIC_A,
            COPA_CLASSIC_B,
            COPA_FUSCA,
            COPA_HOT_CARS,
            COPA_MONTANA,
            COPA_UNO,
            CROSSLE_90F,
            CROSSLE_9S,
            DPI,
            DTM,
            DTM_2002,
            DTM_2003,
            DTM_2005,
            DTM_2013,
            DTM_2014,
            DTM_2015,
            DTM_2016,
            DTM_2020,
            DTM_2026,
            DTM_92,
            DTM_95,
            ESPORTS_WTCR,
            ESPORTS_WTCR_PROLOGUE,
            E_TCR,
            F1,
            F1_2000S,
            F1_2010S,
            F1_2020S,
            F1_70S,
            F1_80S_NA,
            F1_80S_TURBO,
            F1_90S,
            F2,
            F3,
            F4,
            FF,
            FORD_MUSTANG_MACH_E,
            FORMULA_E_2018,
            FORMULA_E_2019,
            FORMULA_FORD_1600,
            FORMULA_RENAULT,
            FORMULA_RENAULT20,
            FR500,
            FRX_22_ESPORTS,
            F_VEE,
            G2,
            G3,
            GR2_70S,
            GR4_70S,
            GROUP2,
            GROUP4,
            GROUP5,
            GROUP6,
            GROUPA,
            GROUPB,
            GROUPC,
            GT,
            GT1,
            GT1X,
            GT2,
            GT3,
            GT300,
            GT4,
            GT5,
            GT500,
            GT55_SUPERCUP,
            GTC,
            GTE,
            GTLM,
            GTO,
            GTOPEN,
            GTP,
            GTR,
            HILL_CLIMB_ICONS,
            HISTORIC_GT_TOURING,
            HISTORIC_OPENWHEEL,
            HISTORIC_PROTOTYPE,
            HISTORIC_TOURING_1,
            HISTORIC_TOURING_2,
            HYBRID_F1_2022,
            HYPER,
            HYPER_CAR,
            HYPER_CAR_RACE,
            ICONIC,
            INDYCAR,
            INDYCAR_2000,
            INDYCAR_95,
            INDYCAR_98,
            INDYCAR_DALLARA_2011,
            INDYCAR_DALLARA_DW12,
            INDYCAR_PRO_2000,
            INDYCAR_USF_2000,
            ISI_STOCKCAR_2015,
            KART,
            KART_1,
            KART_2,
            KART_F1,
            KART_JUNIOR,
            KART_X30_RENTAL,
            KART_X30_SENIOR,
            KTM_GTX,
            KTM_RR,
            LANCER_CUP,
            LATE_MODEL,
            LM,
            LMDH,
            LMP1,
            LMP2,
            LMP3,
            LMP4,
            LMP900,
            LOTUS_CUP,
            M1_PROCAR,
            MAZDA_MX_5_CUP,
            MCR_2000,
            MEGANE_TROPHY,
            MERCEDES_AMG_MOTORSPORT,
            MERCEDES_AMG_MOTORSPORT_30_YEARS_OF_DTM,
            MINI_CHALLENGE,
            MX5_TROPHY,
            NASCAR_1987,
            NASCAR_2016,
            NASCAR_GEN4,
            NASCAR_NEXT_GEN,
            NASCAR_TRUCK,
            NASCAR_XFINITY,
            NGT,
            NSU_TT,
            NXT_GEN_CUP,
            OPALA_STOCK_79,
            OPALA_STOCK_86,
            OPALA_STOCK_OLD,
            OPENWHEEL,
            P1,
            P2,
            P3,
            P4,
            PALATOV_D4_CUSTOM,
            PALATOV_D4_HILLCLIMB,
            PALATOV_D4_TRACKDAY,
            PORSCHE_944_TURBO_CUP,
            PORSCHE_964_CUP,
            PORSCHE_GT2RS,
            PORSCHE_MISSION_R,
            PRAGA_R1,
            PROTOTYPE,
            R3E_SILHOUETTE,
            RACEROOM_ESPORTS,
            RADICAL_SR3,
            REIZA_FV12,
            ROAD_A,
            ROAD_B,
            ROAD_C1,
            ROAD_C2,
            ROAD_D,
            ROAD_E,
            ROAD_F,
            ROAD_G,
            ROAD_SUPERCAR,
            RS01_TROPHY,
            SAFETY_CARS,
            SHOPPING_CART,
            SILHOUETTE_GT,
            SKIP_BARBER,
            SPEC_MIATA,
            SPORTS_CAR_67,
            SPRINT_RACE,
            STOCK_V8,
            STOCK_V8_2020,
            STOCK_V8_2023,
            STOCK_V8_PRO,
            SUPERKART,
            SUPER_RACER,
            SUPER_TOURING,
            TC1,
            TC1_2014,
            TC2,
            TCR,
            TOURING,
            TOYOTA_GR86,
            TRACKDAY_A,
            TRACKDAY_B,
            TRANS_AM,
            TRUCK,
            V8_SUPERCAR,
            VINTAGE_F1_A,
            VINTAGE_F1_A1,
            VINTAGE_F1_B,
            VINTAGE_F1_C,
            VINTAGE_F3_A,
            VINTAGE_GT500,
            VINTAGE_GT_C,
            VINTAGE_GT_D,
            VINTAGE_GT_TOURING,
            VINTAGE_INDY_65,
            VINTAGE_PROTOTYPE_B,
            VINTAGE_STOCK_CAR,
            VOLKSWAGEN_ID_R,
            WRX,
            ZONDA_R_CUP,

            UNKNOWN_RACE,
            USER_CREATED,
        }

        private static Dictionary<TyreType, List<CornerData.EnumWithThresholds>> tyreTempThresholds = new Dictionary<TyreType, List<CornerData.EnumWithThresholds>>();
        private static Dictionary<BrakeType, List<CornerData.EnumWithThresholds>> brakeTempThresholds = new Dictionary<BrakeType, List<CornerData.EnumWithThresholds>>();

        private static Dictionary<string, List<CarClassEnum>> groupedClasses = new Dictionary<string, List<CarClassEnum>>();

        // these are set from R3E data
        public static Dictionary<Tuple<CarClassEnum, TyreType>, List<CornerData.EnumWithThresholds>> optimalTempsFromGame = new Dictionary<Tuple<CarClassEnum, TyreType>, List<CornerData.EnumWithThresholds>>();

        static CarData()
        {
            List<CarClassEnum> r3eDTMClasses = new List<CarClassEnum>();
            r3eDTMClasses.Add(CarClassEnum.DTM_2013); r3eDTMClasses.Add(CarClassEnum.DTM_2014); r3eDTMClasses.Add(CarClassEnum.DTM_2015); r3eDTMClasses.Add(CarClassEnum.DTM_2016);
            groupedClasses.Add("DTM", r3eDTMClasses);

            List<CarClassEnum> r3eTC1Classes = new List<CarClassEnum>();
            r3eTC1Classes.Add(CarClassEnum.TC1); r3eTC1Classes.Add(CarClassEnum.TC1_2014);
            groupedClasses.Add("TC1", r3eTC1Classes);

            List<CornerData.EnumWithThresholds> roadTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            roadTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdRoadTyreTempPeak));
            roadTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdRoadTyreTempPeak, maxWarmRoadTyreTempPeak));
            roadTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmRoadTyreTempPeak, maxHotRoadTyreTempPeak));
            roadTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotRoadTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Road, roadTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> hyperSoftTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            hyperSoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdUltraSoftTyreTempPeak));
            hyperSoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdHyperSoftTyreTempPeak, maxWarmHyperSoftTyreTempPeak));
            hyperSoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmHyperSoftTyreTempPeak, maxHotHyperSoftTyreTempPeak));
            hyperSoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotHyperSoftTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Hyper_Soft, hyperSoftTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> ultraSoftTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            ultraSoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdUltraSoftTyreTempPeak));
            ultraSoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdUltraSoftTyreTempPeak, maxWarmUltraSoftTyreTempPeak));
            ultraSoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmUltraSoftTyreTempPeak, maxHotUltraSoftTyreTempPeak));
            ultraSoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotUltraSoftTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Ultra_Soft, ultraSoftTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> superSoftTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            superSoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdSuperSoftTyreTempPeak));
            superSoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdSuperSoftTyreTempPeak, maxWarmSuperSoftTyreTempPeak));
            superSoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmSuperSoftTyreTempPeak, maxHotSuperSoftTyreTempPeak));
            superSoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotSuperSoftTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Super_Soft, superSoftTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> softTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            softTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdSoftTyreTempPeak));
            softTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdSoftTyreTempPeak, maxWarmSoftTyreTempPeak));
            softTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmSoftTyreTempPeak, maxHotSoftTyreTempPeak));
            softTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotSoftTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Soft, softTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> mediumTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            mediumTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdMediumTyreTempPeak));
            mediumTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdMediumTyreTempPeak, maxWarmMediumTyreTempPeak));
            mediumTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmMediumTyreTempPeak, maxHotMediumTyreTempPeak));
            mediumTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotMediumTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Medium, mediumTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> hardTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            hardTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdHardTyreTempPeak));
            hardTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdHardTyreTempPeak, maxWarmHardTyreTempPeak));
            hardTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmHardTyreTempPeak, maxHotHardTyreTempPeak));
            hardTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotHardTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Hard, hardTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> wetTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            wetTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdWetTyreTempPeak));
            wetTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdWetTyreTempPeak, maxWarmWetTyreTempPeak));
            wetTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmWetTyreTempPeak, maxHotWetTyreTempPeak));
            wetTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotWetTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Wet, wetTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> intermediateTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            intermediateTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdIntermediateTyreTempPeak));
            intermediateTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdIntermediateTyreTempPeak, maxWarmIntermediateTyreTempPeak));
            intermediateTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmIntermediateTyreTempPeak, maxHotIntermediateTyreTempPeak));
            intermediateTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotIntermediateTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Intermediate, intermediateTyreTempsThresholds);
            
            List<CornerData.EnumWithThresholds> iceTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            iceTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdIceTyreTempPeak));
            iceTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdIceTyreTempPeak, maxWarmIceTyreTempPeak));
            iceTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmIceTyreTempPeak, maxHotIceTyreTempPeak));
            iceTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotIceTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Ice, iceTyreTempsThresholds);
            
            List<CornerData.EnumWithThresholds> snowTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            snowTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdSnowTyreTempPeak));
            snowTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdSnowTyreTempPeak, maxWarmSnowTyreTempPeak));
            snowTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmSnowTyreTempPeak, maxHotSnowTyreTempPeak));
            snowTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotSnowTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Snow, snowTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> allTerrainTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            allTerrainTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdAllTerrainTyreTempPeak));
            allTerrainTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdAllTerrainTyreTempPeak, maxWarmAllTerrainTyreTempPeak));
            allTerrainTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmAllTerrainTyreTempPeak, maxHotAllTerrainTyreTempPeak));
            allTerrainTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotAllTerrainTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.AllTerrain, allTerrainTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> unknownRaceTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            unknownRaceTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdUnknownRaceTyreTempPeak));
            unknownRaceTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdUnknownRaceTyreTempPeak, maxWarmUnknownRaceTyreTempPeak));
            unknownRaceTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmUnknownRaceTyreTempPeak, maxHotUnknownRaceTyreTempPeak));
            unknownRaceTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotUnknownRaceTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Unknown_Race, unknownRaceTyreTempsThresholds);

            // to ensure uninitialized tyres still have some thresholds associated with them
            tyreTempThresholds.Add(TyreType.Uninitialized, unknownRaceTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> biasPlyTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            biasPlyTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdBiasPlyTyreTempPeak));
            biasPlyTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdBiasPlyTyreTempPeak, maxWarmBiasPlyTyreTempPeak));
            biasPlyTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmBiasPlyTyreTempPeak, maxHotBiasPlyTyreTempPeak));
            biasPlyTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotBiasPlyTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Bias_Ply, biasPlyTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> r3e2017F5TyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            r3e2017F5TyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdR3E2017F5TyreTempPeak));
            r3e2017F5TyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdR3E2017F5TyreTempPeak, maxWarmR3E2017F5TyreTempPeak));
            r3e2017F5TyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmR3E2017F5TyreTempPeak, maxHotR3E2017F5TyreTempPeak));
            r3e2017F5TyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotR3E2017F5TyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.R3E_2017_F5, r3e2017F5TyreTempsThresholds);

            List<CornerData.EnumWithThresholds> r3e2017SoftTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            r3e2017SoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdR3E2017SoftTyreTempPeak));
            r3e2017SoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdR3E2017SoftTyreTempPeak, maxWarmR3E2017SoftTyreTempPeak));
            r3e2017SoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmR3E2017SoftTyreTempPeak, maxHotR3E2017SoftTyreTempPeak));
            r3e2017SoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotR3E2017SoftTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.R3E_2017_SOFT, r3e2017SoftTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> r3e2017MediumTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            r3e2017MediumTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdR3E2017MediumTyreTempPeak));
            r3e2017MediumTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdR3E2017MediumTyreTempPeak, maxWarmR3E2017MediumTyreTempPeak));
            r3e2017MediumTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmR3E2017MediumTyreTempPeak, maxHotR3E2017MediumTyreTempPeak));
            r3e2017MediumTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotR3E2017MediumTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.R3E_2017_MEDIUM, r3e2017MediumTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> r3e2017HardTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            r3e2017HardTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdR3E2017HardTyreTempPeak));
            r3e2017HardTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdR3E2017HardTyreTempPeak, maxWarmR3E2017HardTyreTempPeak));
            r3e2017HardTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmR3E2017HardTyreTempPeak, maxHotR3E2017HardTyreTempPeak));
            r3e2017HardTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotR3E2017HardTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.R3E_2017_HARD, r3e2017HardTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> r3e2016PrimeTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            r3e2016PrimeTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdR3E2016PrimeTyreTempPeak));
            r3e2016PrimeTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdR3E2016PrimeTyreTempPeak, maxWarmR3E2016PrimeTyreTempPeak));
            r3e2016PrimeTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmR3E2016PrimeTyreTempPeak, maxHotR3E2016PrimeTyreTempPeak));
            r3e2016PrimeTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotR3E2016PrimeTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Prime, r3e2016PrimeTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> r3e2016OptionTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            r3e2016OptionTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdR3E2016OptionTyreTempPeak));
            r3e2016OptionTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdR3E2016OptionTyreTempPeak, maxWarmR3E2016OptionTyreTempPeak));
            r3e2016OptionTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmR3E2016OptionTyreTempPeak, maxHotR3E2016OptionTyreTempPeak));
            r3e2016OptionTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotR3E2016OptionTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.Option, r3e2016OptionTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> r3e2016HardTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            r3e2016HardTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdR3E2016HardTyreTempPeak));
            r3e2016HardTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdR3E2016HardTyreTempPeak, maxWarmR3E2016HardTyreTempPeak));
            r3e2016HardTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmR3E2016HardTyreTempPeak, maxHotR3E2016HardTyreTempPeak));
            r3e2016HardTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotR3E2016HardTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.R3E_2016_HARD, r3e2016HardTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> r3e2016MediumTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            r3e2016MediumTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdR3E2016MediumTyreTempPeak));
            r3e2016MediumTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdR3E2016MediumTyreTempPeak, maxWarmR3E2016MediumTyreTempPeak));
            r3e2016MediumTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmR3E2016MediumTyreTempPeak, maxHotR3E2016MediumTyreTempPeak));
            r3e2016MediumTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotR3E2016MediumTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.R3E_2016_MEDIUM, r3e2016MediumTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> r3e2016SoftTyreTempsThresholds = new List<CornerData.EnumWithThresholds>();
            r3e2016SoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, maxColdR3E2016SoftTyreTempPeak));
            r3e2016SoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, maxColdR3E2016SoftTyreTempPeak, maxWarmR3E2016SoftTyreTempPeak));
            r3e2016SoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, maxWarmR3E2016SoftTyreTempPeak, maxHotR3E2016SoftTyreTempPeak));
            r3e2016SoftTyreTempsThresholds.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, maxHotR3E2016SoftTyreTempPeak, 10000));
            tyreTempThresholds.Add(TyreType.R3E_2016_SOFT, r3e2016SoftTyreTempsThresholds);

            List<CornerData.EnumWithThresholds> ironRoadBrakeTempsThresholds = new List<CornerData.EnumWithThresholds>();
            ironRoadBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.COLD, -10000, maxColdIronRoadBrakeTemp));
            ironRoadBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.WARM, maxColdIronRoadBrakeTemp, maxWarmIronRoadBrakeTemp));
            ironRoadBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.HOT, maxWarmIronRoadBrakeTemp, maxHotIronRoadBrakeTemp));
            ironRoadBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.COOKING, maxHotIronRoadBrakeTemp, 10000));
            brakeTempThresholds.Add(BrakeType.Iron_Road, ironRoadBrakeTempsThresholds);

            List<CornerData.EnumWithThresholds> ironRaceBrakeTempsThresholds = new List<CornerData.EnumWithThresholds>();
            ironRaceBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.COLD, -10000, maxColdIronRaceBrakeTemp));
            ironRaceBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.WARM, maxColdIronRaceBrakeTemp, maxWarmIronRaceBrakeTemp));
            ironRaceBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.HOT, maxWarmIronRaceBrakeTemp, maxHotIronRaceBrakeTemp));
            ironRaceBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.COOKING, maxHotIronRaceBrakeTemp, 10000));
            brakeTempThresholds.Add(BrakeType.Iron_Race, ironRaceBrakeTempsThresholds);

            List<CornerData.EnumWithThresholds> ceramicBrakeTempsThresholds = new List<CornerData.EnumWithThresholds>();
            ceramicBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.COLD, -10000, maxColdCeramicBrakeTemp));
            ceramicBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.WARM, maxColdCeramicBrakeTemp, maxWarmCeramicBrakeTemp));
            ceramicBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.HOT, maxWarmCeramicBrakeTemp, maxHotCeramicBrakeTemp));
            ceramicBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.COOKING, maxHotCeramicBrakeTemp, 10000));
            brakeTempThresholds.Add(BrakeType.Ceramic, ceramicBrakeTempsThresholds);

            List<CornerData.EnumWithThresholds> carbonBrakeTempsThresholds = new List<CornerData.EnumWithThresholds>();
            carbonBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.COLD, -10000, maxColdCarbonBrakeTemp));
            carbonBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.WARM, maxColdCarbonBrakeTemp, maxWarmCarbonBrakeTemp));
            carbonBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.HOT, maxWarmCarbonBrakeTemp, maxHotCarbonBrakeTemp));
            carbonBrakeTempsThresholds.Add(new CornerData.EnumWithThresholds(BrakeTemp.COOKING, maxHotCarbonBrakeTemp, 10000));
            brakeTempThresholds.Add(BrakeType.Carbon, carbonBrakeTempsThresholds);
        }

        public class CarClassEnumConverter : Newtonsoft.Json.Converters.StringEnumConverter
        {
            public override object ReadJson(JsonReader reader, Type objectType, object existingValue, JsonSerializer serializer)
            {
                var className = (string)reader.Value;
                CarClassEnum carClassID = CarClassEnum.UNKNOWN_RACE;
                if (Enum.TryParse<CarClassEnum>(className, out carClassID) && Enum.IsDefined(typeof(CarClassEnum), carClassID))
                {
                    return carClassID;
                }
                else
                {
                    // no match - we really don't know what this class is, so create one
                    Console.WriteLine("Car class enum for " + className + " not found");
                    userCarClassIds.Add(className);
                    return CarClassEnum.USER_CREATED;
                }
            }
        }

        private static CarClasses CAR_CLASSES;

        // used for PCars only, where we only know if the opponent is the same class as us or not
        public static CarClass DEFAULT_PCARS_OPPONENT_CLASS = new CarClass();

        private static Dictionary<string, CarClass> classNameToCarClass;
        private static Dictionary<string, CarClass> carNameToCarClass;
        private static Dictionary<int, CarClass> intToCarClass;

        private static Dictionary<int, CarClass> iracingCarIdToCarClass;
        private static Dictionary<int, CarClass> iracingCarClassIdToCarClass;

        private static List<String> userCarClassIds = new List<string>();
        public static int RACEROOM_CLASS_ID = -1;
        public static int IRACING_CLASS_ID = -1;
        public static String CLASS_ID = "";

        public static void clearCachedIRacingClassData() {
            iracingCarClassIdToCarClass.Clear();
            iracingCarIdToCarClass.Clear();
        }

        public class TyreTypeData
        {
            public float maxColdTyreTemp { get; set; }
            public float maxWarmTyreTemp { get; set; }
            public float maxHotTyreTemp { get; set; }
        }
        /// <summary>
        /// Loaded from carClassData.json
        /// </summary>
        public class CarClass
        {
            [JsonConverter(typeof(CarClassEnumConverter))]
            public CarClassEnum carClassEnum { get; set; }
            public Int32 ClassPerformanceIndex { get; set; } // used in R3E
            public List<int> raceroomClassIds { get; set; }
            public List<int> iracingCarIds { get; set; }
            public List<string> pCarsClassNames { get; set; }
            public List<string> pCarsCarNames { get; set; } // if this is set on a car class this is used instead of the class name
            public List<string> rf1ClassNames { get; set; }
            public List<string> ams2ClassNames { get; set; }
            public List<string> rf2ClassNames { get; set; }
            public List<string> lmuClassNames { get; set; }
            public List<string> acClassNames { get; set; }
            public List<string> aceCarNames { get; set; }
            public List<string> gtr2ClassNames { get; set; }

            [JsonConverter(typeof(StringEnumConverter))]
            public BrakeType brakeType { get; set; }
            public float maxColdBrakeTemp { get; set; }
            public float maxWarmBrakeTemp { get; set; }
            public float maxHotBrakeTemp { get; set; }

            [JsonConverter(typeof(StringEnumConverter))]
            public TyreType defaultTyreType { get; set; }
            public Dictionary<string, TyreTypeData> acTyreTypeData { get; set; }
            public float maxColdTyreTemp { get; set; }
            public float maxWarmTyreTemp { get; set; }
            public float maxHotTyreTemp { get; set; }

            public float maxSafeWaterTemp { get; set; }
            public float maxSafeOilTemp { get; set; }
            public float minTyreCircumference { get; set; }
            public float maxTyreCircumference { get; set; }
            public float spotterVehicleWidth { get; set; }
            public float spotterVehicleLength { get; set; }

            public bool timesInHundredths { get; set; }
            public bool useAmericanTerms { get; set; }
            public String enabledMessageTypes { get; set; }
            public bool isDRSCapable { get; set; }
            public float DRSRange { get; set; }
            public int pitCrewPreparationTime { get; set; }
            public bool isBatteryPowered { get; set; }
            public bool isVehicleSwapAllowed { get; set; }
            public bool isRefuelingAllowed { get; set; }
            public bool limiterAvailable { get; set; }
            public bool allMembersAreFWD { get; set; }
            public bool allMembersAreRWD { get; set; }
            public bool preferNameForOrderMessages { get; set; }
            public Dictionary<string, TyreType> gameTyreToTyreType { get; set; }

            public String placeholderClassId = "";

            public Boolean grouped = false;

            public List<Regex> pCarsClassNamesRegexs = new List<Regex>();
            public List<Regex> rf1ClassNamesRegexs = new List<Regex>();
            public List<Regex> ams2ClassNamesRegexs = new List<Regex>();
            public List<Regex> rf2ClassNamesRegexs = new List<Regex>();
            public List<Regex> lmuClassNamesRegexs = new List<Regex>();
            public List<Regex> acClassNamesRegexs = new List<Regex>();
            public List<Regex> aceClassNamesRegexs = new List<Regex>();
            public List<Regex> gtr2ClassNamesRegexs = new List<Regex>();

            // Turns out enum.ToString() is costly, so cache string representation of enum value.
            public String carClassEnumString = null;
            public CarClass()
            {
                // initialise with default values
                this.carClassEnum = CarClassEnum.UNKNOWN_RACE;
                this.raceroomClassIds = new List<int>();
                this.iracingCarIds = new List<int>();
                this.pCarsClassNames = new List<string>();
                this.pCarsCarNames = new List<string>();
                this.rf1ClassNames = new List<string>();
                this.ams2ClassNames = new List<string>();
                this.rf2ClassNames = new List<string>();
                this.lmuClassNames = new List<string>();
                this.acClassNames = new List<string>();
                this.aceCarNames = new List<string>();
                this.gtr2ClassNames = new List<string>();
                this.brakeType = BrakeType.Iron_Race;
                this.maxColdBrakeTemp = -1;
                this.maxWarmBrakeTemp = -1;
                this.maxHotBrakeTemp = -1;
                this.defaultTyreType = TyreType.Unknown_Race;
                this.acTyreTypeData = new Dictionary<string, TyreTypeData>();
                this.maxColdTyreTemp = -1;
                this.maxWarmTyreTemp = -1;
                this.maxHotTyreTemp = -1;
                this.maxSafeWaterTemp = 115;
                this.maxSafeOilTemp = 130;
                this.minTyreCircumference = 0.5f * (float)Math.PI;
                this.maxTyreCircumference = 1.2f * (float)Math.PI;
                this.enabledMessageTypes = "";
                this.isDRSCapable = false;
                this.DRSRange = -1.0f;
                this.pitCrewPreparationTime = 25;
                this.isBatteryPowered = false;
                this.isVehicleSwapAllowed = false;
                this.isRefuelingAllowed = true;
                this.limiterAvailable = true;
                this.preferNameForOrderMessages = false;
                this.gameTyreToTyreType = new Dictionary<string, TyreType>();
            }


            public String getClassIdentifier()
            {
                if (this.carClassEnum == CarClassEnum.UNKNOWN_RACE || this.carClassEnum == CarClassEnum.USER_CREATED)
                {
                    // this class has been generated from an unrecognised ID, so return the
                    // ID we used to generate this new class.
                    return placeholderClassId;
                }
                else
                {
                    if (this.carClassEnumString == null)
                    {
                        // if this car class is part of a group, the class identifier will be the group name, 
                        // not the enum name. This dictionary lookup and iteration is only done once per class because
                        // the result is cached, so this shouldn't affect performance too much
                        foreach (KeyValuePair<string, List<CarClassEnum>> keyValuePair in groupedClasses)
                        {
                            foreach (CarClassEnum carClassEnum in keyValuePair.Value)
                            {
                                if (carClassEnum == this.carClassEnum)
                                {
                                    this.carClassEnumString = keyValuePair.Key;
                                    grouped = true;
                                    break;
                                }
                            }
                            if (grouped)
                            {
                                break;
                            }
                        }
                        if (!grouped)
                        {
                            this.carClassEnumString = this.carClassEnum.ToString();
                        }
                    }
                    return this.carClassEnumString;
                }
            }

            public void setupRegexs()
            {
                setupRegexs(rf1ClassNames, rf1ClassNamesRegexs);
                setupRegexs(ams2ClassNames, ams2ClassNamesRegexs);
                setupRegexs(rf2ClassNames, rf2ClassNamesRegexs);
                setupRegexs(lmuClassNames, lmuClassNamesRegexs);
                setupRegexs(acClassNames, acClassNamesRegexs);
                setupRegexs(aceCarNames, aceClassNamesRegexs);
                setupRegexsForPCars(pCarsClassNames, pCarsClassNamesRegexs);
                setupRegexs(gtr2ClassNames, gtr2ClassNamesRegexs);
            }

            /**
             * Create regexs for classnames with wildcards.
             */
            private void setupRegexs(List<string> classNames, List<Regex> regexs)
            {
                foreach (String className in classNames)
                {
                    if (className.Count() > 0)
                    {
                        if (className.Contains("*") || className.Contains("?"))
                        {
                            String regexStr = wildcardToRegex(className);
                            regexs.Add(new Regex(regexStr, RegexOptions.IgnoreCase));
                        }
                    }
                }
            }

            /**
             * Separate method for Pcars which adds a copy of each classname with the null-standin char as the first char - 
             * i.e. "GT3" has another class called "?T3" for when PCars deems the first character of the classname unimportant.
             * Note that we also do this for regexs but only if they don't already start with a wildcard.
             * 
             */
            private void setupRegexsForPCars(List<string> classNames, List<Regex> regexs)
            {
                List<String> classesWithNullStandinChar = new List<string>();
                foreach (String className in classNames)
                {
                    if (className.Count() > 0)
                    {
                        if (className.Contains("*") || className.Contains("?"))
                        {
                            String regexStr = wildcardToRegex(className);
                            regexs.Add(new Regex(regexStr, RegexOptions.IgnoreCase));
                            if (!className.StartsWith("*") && !className.StartsWith("?"))
                            {
                                // sometimes PCars sends null instead of the proper first char of the String. We replace this with "?", 
                                // so assemble another regex here who's first 2 characters are replaced with the literal "^?", but only
                                // if this regex doesn't start with a wildcard
                                regexs.Add(new Regex("^\\" + PCarsGameStateMapper.NULL_CHAR_STAND_IN + regexStr.Substring(2), RegexOptions.IgnoreCase));
                            }
                        }
                        // sometimes PCars sends null instead of the proper first char of the String. We replace this with "?", 
                        // add another class name here who's first character is replaced with "?"
                        classesWithNullStandinChar.Add(PCarsGameStateMapper.NULL_CHAR_STAND_IN + className.Substring(1));
                    }
                }
                classNames.AddRange(classesWithNullStandinChar);
            }

            private String wildcardToRegex(string pattern)
            {
                return "^" + Regex.Escape(pattern).Replace("\\*", ".*").Replace("\\?", ".") + "$";
            }
        }

        public class CarClasses
        {
            public List<CarClass> carClasses { get; set; }
            public CarClasses()
            {
                this.carClasses = new List<CarClass>();
            }
        }

        /// <summary>
        /// If multi-class racing, are two cars in the same class. Or do they have the same R3E_Perf_Index?
        /// </summary>
        /// <param name="assumeEqualIfSingleClass">does something if false...</param>
        public static Boolean IsCarClassEqual(CarClass class1, CarClass class2, Boolean assumeEqualIfSingleClass = true)
        {
            // if multiclass is disabled (from UI setting or because of unusable car class data) then in *most*
            // cases we can assume all car classes are equal. The exception here is when checking if the player's
            // car class has changed (done as part of the new session logic).
            if (assumeEqualIfSingleClass && (CrewChief.forceSingleClass || !GameStateData.Multiclass))
            {
                return true;
            }
            if (class1 == class2)
            {
                return true;
            }
            if (class1 == null && class2 != null)
            {
                return false;
            }
            if (class2 == null && class1 != null)
            {
                return false;
            }
            // check gropued classes separately
            if (class1.grouped && class2.grouped && String.Equals(class1.getClassIdentifier(), class2.getClassIdentifier()))
            {
                return true;
            }
            if (class1.carClassEnum == class2.carClassEnum)
            {
                // If car class enums are matching, we need to check if it isn't a special case of
                // ambigous enums, that is UNKNOWN_RACE or USER_CREATED.  Both of those can only be disambiguated
                // via identifier comparison.
                if ((class1.carClassEnum == CarClassEnum.UNKNOWN_RACE || class1.carClassEnum == CarClassEnum.USER_CREATED)
                    && (class2.carClassEnum == CarClassEnum.UNKNOWN_RACE || class2.carClassEnum == CarClassEnum.USER_CREATED)
                    && !String.Equals(class1.getClassIdentifier(), class2.getClassIdentifier()))
                {
                    return false;  // Both are UNKNOWN_RACE/USER_CREATED, but identifiers don't match.  Those are different classes.
                }

                return true;  // Same, unambigous enum values, classes are equal.
            }

            if (class1.ClassPerformanceIndex != 0 && class1.ClassPerformanceIndex == class2.ClassPerformanceIndex)
            {
                return true;
            }

            // The grouping is processed in the getClassIdentifier method, so we don't need to check for it here
            return false;
        }

        public static void loadCarClassData()
        {
            userCarClassIds = new List<string>();
            CarClasses defaultCarClassData = getCarClassDataFromFile(getDefaultCarClassFileLocation());
            CarClasses userCarClassData = getCarClassDataFromFile(getUserCarClassFileLocation());
            mergeCarClassData(defaultCarClassData, userCarClassData);
            foreach (CarClass carClass in userCarClassData.carClasses)
            {
                carClass.setupRegexs();
                // eagerly initialise these - this ensures the grouped flag is set correctly from the outset
                carClass.getClassIdentifier();
            }
            CAR_CLASSES = userCarClassData;

            // reset session scoped cache of class name / ID to CarClass Dictionary.
            classNameToCarClass = new Dictionary<string, CarClass>();
            carNameToCarClass = new Dictionary<string, CarClass>();
            intToCarClass = new Dictionary<int, CarClass>();
            iracingCarIdToCarClass = new Dictionary<int, CarClass>();
            iracingCarClassIdToCarClass = new Dictionary<int, CarClass>();
        }

        private static void mergeCarClassData(CarClasses defaultCarClassData, CarClasses userCarClassData)
        {
            int userCarClassesCount = 0;
            List<CarClass> classesToAddFromDefault = new List<CarClass>();
            foreach (CarClass defaultCarClass in defaultCarClassData.carClasses)
            {
                Boolean isInUserCarClasses = false;
                int userCarClassIndex = 0;
                foreach (CarClass userCarClass in userCarClassData.carClasses)
                {
                    if (userCarClass.carClassEnum == defaultCarClass.carClassEnum)
                    {
                        isInUserCarClasses = true;
                        userCarClassesCount++;
                        break;
                    }
                    else if (userCarClass.carClassEnum == CarClassEnum.USER_CREATED && userCarClass.placeholderClassId.Length == 0 &&
                        userCarClassIds.Count > userCarClassIndex)
                    {
                        userCarClass.placeholderClassId = userCarClassIds[userCarClassIndex];
                        Console.WriteLine("Adding a user defined class with ID " + userCarClass.placeholderClassId);
                        userCarClassIndex++;
                        userCarClassesCount++;
                    }
                }
                if (!isInUserCarClasses)
                {
                    classesToAddFromDefault.Add(defaultCarClass);
                }
            }
            userCarClassData.carClasses.AddRange(classesToAddFromDefault);
            Console.WriteLine("Loaded " + defaultCarClassData.carClasses.Count + " default car class definitions and " +
                userCarClassesCount + " user defined car class definitions");
        }

        private static CarClasses getCarClassDataFromFile(String filename)
        {
            if (filename != null)
            {
                try
                {
                    CarClasses carClass = JsonFiles.ReadFile<CarClasses>(filename, JsonFiles.Comments.Strip);
                    if (carClass != null)
                    {
                        return carClass;
                    }
                }
                catch (Exception e)
                {
                    Log.Exception(e, "Error parsing " + filename + ": ");
                }
            }
            return new CarClasses();
        }

        private static String getDefaultCarClassFileLocation()
        {
            String path = DataFiles.default_carClassData;
            if (File.Exists(path))
            {
                return path;
            }
            else
            {
                return null;
            }
        }

        private static String getUserCarClassFileLocation()
        {
            String path = DataFiles.carClassData;

            if (File.Exists(path))
            {
                Log.Commentary($"Reading supplementary class data from {path}");
                return path;
            }
            else
            {
                return null;
            }
        }

        public static CarClass getCarClassFromEnum(CarClassEnum carClassEnum)
        {
            foreach (CarClass carClass in CAR_CLASSES.carClasses)
            {
                if (carClass.carClassEnum == carClassEnum)
                {
                    return carClass;
                }
            }
            return new CarClass();
        }

        public static CarClass getCarClassForRaceRoomId(int carClassId)
        {
            // first check if it's in the cache
            CarClass carClassCached = null;
            if (intToCarClass.TryGetValue(carClassId, out carClassCached))
            {
                return carClassCached;
            }
            foreach (CarClass carClass in CAR_CLASSES.carClasses)
            {
                if (carClass.raceroomClassIds.Contains(carClassId))
                {
                    Console.WriteLine("Mapped car class from ID:\"{0}\"  to:\"{1}\"", carClassId, carClass.getClassIdentifier());
                    intToCarClass.Add(carClassId, carClass);
                    return carClass;
                }
            }

            // create one if it doesn't exist
            CarClass newCarClass = new CarClass();
            Console.WriteLine("Unmapped car class added:\"{0}\"", carClassId);
            intToCarClass.Add(carClassId, newCarClass);
            newCarClass.placeholderClassId = carClassId.ToString();
            return newCarClass;
        }

        public static CarClass getCarClassForIRacingId(int carClassId, int carId)
        {
            // first check if it's in the one of the caches
            CarClass carClassCached = null;
            if (iracingCarIdToCarClass.TryGetValue(carId, out carClassCached))
            {
                return carClassCached;
            }
            if (iracingCarClassIdToCarClass.TryGetValue(carClassId, out carClassCached))
            {
                return carClassCached;
            }
            foreach (CarClass carClass in CAR_CLASSES.carClasses)
            {
                if (carClass.iracingCarIds.Contains(carId))
                {
                    iracingCarIdToCarClass.Add(carId, carClass);
                    return carClass;
                }
            }

            // create one if it doesn't exist
            CarClass newCarClass = new CarClass();
            iracingCarClassIdToCarClass.Add(carClassId, newCarClass);
            newCarClass.placeholderClassId = carClassId.ToString();
            return newCarClass;
        }
        /// <summary>
        /// Retrieves a CarClass based on the provided class name and optional car name, using game-specific matching logic.
        /// 
        /// This method performs a multi-stage lookup with the following priority:
        /// 1. Checks cache for carName (if provided)
        /// 2. Checks cache for className
        /// 3. Attempts to match carName against known car names for the current game
        /// 4. Attempts to match className against known class names for the current game
        /// 5. Attempts to match className against regex patterns for the current game
        /// 6. Attempts to match className directly against CarClassEnum values
        /// 7. Creates and returns a new unknown CarClass with placeholder ID if no match is found
        /// 
        /// The matching is case-insensitive and game-specific. Different games (ACC, RF1, RF2, PCars, AMS2, etc.)
        /// have different class name properties that are searched based on the current CrewChief.gameDefinition.gameEnum.
        /// 
        /// Results are cached after the first lookup to improve performance on subsequent calls with the same inputs.
        /// </summary>
        /// <param name="className">The class name to search for (e.g., "GT3", "Formula Renault"). Must not be null.</param>
        /// <param name="carName">Optional specific car name to match before falling back to className matching (e.g., "Ferrari 488 GT3"). 
        /// Only used for games that support car-specific class identification (PCars, PCars2, etc.). Defaults to null.</param>
        /// <returns>A CarClass instance. Returns a mapped CarClass if a match is found, or a new unknown CarClass with 
        /// placeholderClassId set to the input className if no match is found. Never returns null.</returns>
        /// <remarks>
        /// 
        /// The method uses reflection to access game-specific property names dynamically based on the current game:
        /// - PCars: pCarsClassNames, pCarsCarNames
        /// - RF1: rf1ClassNames
        /// - RF2: rf2ClassNames
        /// - ACC/Assetto Corsa Competizione: acClassNames
        /// - Assetto EVO: aceClassNames
        /// - AMS2: ams2ClassNames
        /// - GTR2: gtr2ClassNames
        /// - LMU: lmuClassNames
        /// 
        /// Unsupported games return an empty CarClass.
        /// </remarks>
        /// <exception cref="System.ArgumentNullException">Not thrown; null className is handled gracefully by returning an empty CarClass.</exception>
        public static CarClass getCarClassForClassNameOrCarName(String className, String carName = null)
        {
            if (className == null)
            {
                // should we return null here? Throw an IllegalArgumentException?
                Console.WriteLine("Null car class name");
                return new CarClass();
            }
            else
            {
                // first check if it's in the cache
                CarClass cachedCarClass = null;
                if (carName != null && carNameToCarClass.TryGetValue(carName, out cachedCarClass))
                {
                    return cachedCarClass;
                }
                if (classNameToCarClass.TryGetValue(className, out cachedCarClass))
                {
                    return cachedCarClass;
                }
                else
                {
                    String carNamesPropName = null;
                    String classNamesPropName = null;
                    String regexsPropName = null;
                    switch (Game.gameType)
                    {
                        case GameType.PCARS:
                        case GameType.PCARS2:
                        case GameType.PCARS3:
                            carNamesPropName = "pCarsCarNames";
                            classNamesPropName = "pCarsClassNames";
                            regexsPropName = "pCarsClassNamesRegexs";
                            break;
                        case GameType.RF1:
                            classNamesPropName = "rf1ClassNames";
                            regexsPropName = "rf1ClassNamesRegexs";
                            break;
                        case GameType.ASSETTO:
                        case GameType.ASSETTO_RALLY:
                            classNamesPropName = "acClassNames";
                            regexsPropName = "acClassNamesRegexs";
                            break;
                        case GameType.ASSETTO_EVO:
                            carNamesPropName = "aceCarNames";
                            regexsPropName = "aceClassNamesRegexs";
                            break;
                        case GameType.RF2:
                            classNamesPropName = "rf2ClassNames";
                            regexsPropName = "rf2ClassNamesRegexs";
                            break;
                        case GameType.LMU:
                            classNamesPropName = "lmuClassNames";
                            regexsPropName = "lmuClassNamesRegexs";
                            break;
                        case GameType.ACC:
                            classNamesPropName = "acClassNames";
                            regexsPropName = "acClassNamesRegexs";
                            break;
                        case GameType.AMS2:
                            classNamesPropName = "ams2ClassNames";
                            regexsPropName = "ams2ClassNamesRegexs";
                            break;
                        case GameType.GTR2:
                            classNamesPropName = "gtr2ClassNames";
                            regexsPropName = "gtr2ClassNamesRegexs";
                            break;
                        default:
                            // err....
                            return new CarClass();
                    }
                    foreach (CarClass carClass in CAR_CLASSES.carClasses)
                    {
                        if (carName != null && carNamesPropName != null)
                        {
                            List<String> carNames = (List<String>)carClass.GetType().GetProperty(carNamesPropName).GetValue(carClass, null);
                            if (carNames != null)
                            {
                                foreach (String thisCarName in carNames)
                                {
                                    if (string.Compare(thisCarName, carName, StringComparison.InvariantCultureIgnoreCase) == 0)
                                    {
                                        Console.WriteLine("Mapped car class from car name:\"{0}\"  to:\"{1}\"", carName, carClass.getClassIdentifier());
                                        carNameToCarClass.Add(carName, carClass);
                                        return carClass;
                                    }
                                }
                            }
                        }
                        if (classNamesPropName != null)
                        {
                            // Check className
                            List<String> classNames = (List<String>)carClass.GetType().GetProperty(classNamesPropName).GetValue(carClass, null);
                            foreach (String thisClassName in classNames)
                            {
                                if (string.Compare(thisClassName, className, StringComparison.InvariantCultureIgnoreCase) == 0)
                                {
                                    if (carName != null)
                                    {
                                        Console.WriteLine("Mapped car class from ID:\"{0}\"  to:\"{1}\", ignoring carName: \"{2}\"",
                                            className, carClass.getClassIdentifier(), carName);
                                    }
                                    else
                                    {
                                        Console.WriteLine("Mapped car class from ID:\"{0}\"  to:\"{1}\"", className, carClass.getClassIdentifier());
                                    }
                                    classNameToCarClass.Add(className, carClass);
                                    return carClass;
                                }
                            }
                        }
                    }
                    foreach (CarClass carClass in CAR_CLASSES.carClasses)
                    {
                        List<Regex> regexs = (List<Regex>)carClass.GetType().GetField(regexsPropName).GetValue(carClass);
                        foreach (Regex regex in regexs)
                        {
                            if (regex.IsMatch(className))
                            {
                                Console.WriteLine("Mapped car class from ID:\"{0}\"  to:\"{1}\"", className, carClass.getClassIdentifier());
                                classNameToCarClass.Add(className, carClass);
                                return carClass;
                            }
                        }
                    }
                    // no match, try matching on the enum directly
                    CarClassEnum carClassID = CarClassEnum.UNKNOWN_RACE;
                    if (Enum.TryParse<CarClassEnum>(className, out carClassID) && Enum.IsDefined(typeof(CarClassEnum), carClassID))
                    {
                        CarClass existingClass = CarData.getCarClassFromEnum(carClassID);
                        Console.WriteLine("Mapped car class from ID:\"{0}\"  to:\"{1}\"", className, existingClass.getClassIdentifier());
                        classNameToCarClass.Add(className, existingClass);
                        return existingClass;
                    }
                    else
                    {
                        // no match - we really don't know what this class is, so create one
                        CarClass newCarClass = new CarClass();
                        newCarClass.placeholderClassId = className;
                        Console.WriteLine("Unmapped car class added:\"{0}\"", className);
                        classNameToCarClass.Add(className, newCarClass);
                        return newCarClass;
                    }
                }
            }
        }

        public static List<CornerData.EnumWithThresholds> getBrakeTempThresholds(CarClass carClass)
        {
            var predefinedBrakeThresholds = brakeTempThresholds[carClass.brakeType];
            // Copy predefined thresholds to avoid overriding defaults.
            var btt = new List<CornerData.EnumWithThresholds>();
            foreach (var threshold in predefinedBrakeThresholds)
            {
                btt.Add(new CornerData.EnumWithThresholds(threshold.e, threshold.lowerThreshold, threshold.upperThreshold));
            }
            // Apply overrides from .json, if user provided them.
            if (btt.Count == 4) // COLD, WARM, HOT, COOKING thresholds
            {
                // Should we validate thresholds to see if they make any sense?
                if (carClass.maxColdBrakeTemp > 0)
                {
                    Debug.Assert((BrakeTemp)btt[0].e == BrakeTemp.COLD);
                    btt[0].upperThreshold = carClass.maxColdBrakeTemp;
                    Debug.Assert((BrakeTemp)btt[1].e == BrakeTemp.WARM);
                    btt[1].lowerThreshold = carClass.maxColdBrakeTemp;
                }
                if (carClass.maxWarmBrakeTemp > 0)
                {
                    Debug.Assert((BrakeTemp)btt[1].e == BrakeTemp.WARM);
                    btt[1].upperThreshold = carClass.maxWarmBrakeTemp;
                    Debug.Assert((BrakeTemp)btt[2].e == BrakeTemp.HOT);
                    btt[2].lowerThreshold = carClass.maxWarmBrakeTemp;
                }
                if (carClass.maxHotBrakeTemp > 0)
                {
                    Debug.Assert((BrakeTemp)btt[2].e == BrakeTemp.HOT);
                    btt[2].upperThreshold = carClass.maxHotBrakeTemp;
                    Debug.Assert((BrakeTemp)btt[3].e == BrakeTemp.COOKING);
                    btt[3].lowerThreshold = carClass.maxHotBrakeTemp;
                }
            }
            return btt;
        }

        public static TyreType getDefaultTyreType(CarClass carClass)
        {
            return carClass.defaultTyreType;
        }

        public static List<CornerData.EnumWithThresholds> getTyreTempThresholds(CarClass carClass)
        {
            var predefinedTyreThresholds = tyreTempThresholds[carClass.defaultTyreType];
            // Copy predefined thresholds to avoid overriding defaults.
            var ttt = new List<CornerData.EnumWithThresholds>();
            foreach (var threshold in predefinedTyreThresholds)
            {
                ttt.Add(new CornerData.EnumWithThresholds(threshold.e, threshold.lowerThreshold, threshold.upperThreshold));
            }
            // Apply overrides from .json, if user provided them.
            if (ttt.Count == 4) // COLD, WARM, HOT, COOKING thresholds
            {
                // Should we validate thresholds to see if they make any sense?
                if (carClass.maxColdTyreTemp > 0)
                {
                    Debug.Assert((TyreTemp)ttt[0].e == TyreTemp.COLD);
                    ttt[0].upperThreshold = carClass.maxColdTyreTemp;
                    Debug.Assert((TyreTemp)ttt[1].e == TyreTemp.WARM);
                    ttt[1].lowerThreshold = carClass.maxColdTyreTemp;
                }
                if (carClass.maxWarmTyreTemp > 0)
                {
                    Debug.Assert((TyreTemp)ttt[1].e == TyreTemp.WARM);
                    ttt[1].upperThreshold = carClass.maxWarmTyreTemp;
                    Debug.Assert((TyreTemp)ttt[2].e == TyreTemp.HOT);
                    ttt[2].lowerThreshold = carClass.maxWarmTyreTemp;
                }
                if (carClass.maxHotTyreTemp > 0)
                {
                    Debug.Assert((TyreTemp)ttt[2].e == TyreTemp.HOT);
                    ttt[2].upperThreshold = carClass.maxHotTyreTemp;
                    Debug.Assert((TyreTemp)ttt[3].e == TyreTemp.COOKING);
                    ttt[3].lowerThreshold = carClass.maxHotTyreTemp;
                }
            }
            return ttt;
        }

        public static void AddTempThresholdsFromGame(Tuple<CarClassEnum, TyreType> key, float coldTemp, float optimalTemp, float hotTemp)
        {
            float coldThreshold = optimalTemp - (optimalTemp - coldTemp) / 2;
            float hotThreshold = hotTemp - (hotTemp - optimalTemp) / 2;
            float cookingThresold = hotTemp + (hotTemp - optimalTemp) / 2;
            List<CornerData.EnumWithThresholds> thresholdsFromGameData = new List<CornerData.EnumWithThresholds>();
            thresholdsFromGameData.Add(new CornerData.EnumWithThresholds(TyreTemp.COLD, -10000, coldThreshold));
            thresholdsFromGameData.Add(new CornerData.EnumWithThresholds(TyreTemp.WARM, coldThreshold, hotThreshold));
            thresholdsFromGameData.Add(new CornerData.EnumWithThresholds(TyreTemp.HOT, hotThreshold, cookingThresold));
            thresholdsFromGameData.Add(new CornerData.EnumWithThresholds(TyreTemp.COOKING, cookingThresold, 10000));
            CarData.optimalTempsFromGame[key] = thresholdsFromGameData;
        }

        public static List<CornerData.EnumWithThresholds> getTyreTempThresholds(CarClass carClass, TyreType tyreType)
        {
            List<CornerData.EnumWithThresholds> predefinedTyreThresholds;
            var key = new Tuple<CarClassEnum, TyreType>(carClass.carClassEnum, tyreType);
            if (Game.RACE_ROOM && CarData.optimalTempsFromGame.ContainsKey(key))
            {
                predefinedTyreThresholds = CarData.optimalTempsFromGame[key];
            }
            else
            {
                if (!tyreTempThresholds.ContainsKey(tyreType))
                {
                    tyreType = TyreType.Unknown_Race;
                }
                predefinedTyreThresholds = tyreTempThresholds[tyreType];
            }
            // Copy predefined thresholds to avoid overriding defaults.
            var ttt = new List<CornerData.EnumWithThresholds>();
            foreach (var threshold in predefinedTyreThresholds)
            {
                ttt.Add(new CornerData.EnumWithThresholds(threshold.e, threshold.lowerThreshold, threshold.upperThreshold));
            }
            // Apply overrides from .json, if user provided them.
            if (ttt.Count == 4) // COLD, WARM, HOT, COOKING thresholds
            {
                // Should we validate thresholds to see if they make any sense?
                if (carClass.maxColdTyreTemp > 0)
                {
                    Debug.Assert((TyreTemp)ttt[0].e == TyreTemp.COLD);
                    ttt[0].upperThreshold = carClass.maxColdTyreTemp;
                    Debug.Assert((TyreTemp)ttt[1].e == TyreTemp.WARM);
                    ttt[1].lowerThreshold = carClass.maxColdTyreTemp;
                }
                if (carClass.maxWarmTyreTemp > 0)
                {
                    Debug.Assert((TyreTemp)ttt[1].e == TyreTemp.WARM);
                    ttt[1].upperThreshold = carClass.maxWarmTyreTemp;
                    Debug.Assert((TyreTemp)ttt[2].e == TyreTemp.HOT);
                    ttt[2].lowerThreshold = carClass.maxWarmTyreTemp;
                }
                if (carClass.maxHotTyreTemp > 0)
                {
                    Debug.Assert((TyreTemp)ttt[2].e == TyreTemp.HOT);
                    ttt[2].upperThreshold = carClass.maxHotTyreTemp;
                    Debug.Assert((TyreTemp)ttt[3].e == TyreTemp.COOKING);
                    ttt[3].lowerThreshold = carClass.maxHotTyreTemp;
                }
            }
            return ttt;
        }
    }
}
