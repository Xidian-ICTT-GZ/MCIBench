package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/m1inato/mcibench-board/internal/model"
)

// GetStatsOverview 返回仪表盘概览统计数据。
func (h *Handler) GetStatsOverview(c *gin.Context) {
	var problemCount, generationBenchmarkCount, translationBenchmarkCount, submissionCount, genCodeCount, translationCount int64
	h.DB.Model(&model.Problem{}).Count(&problemCount)
	h.DB.Model(&model.Problem{}).Where("is_generation_benchmark = ?", true).Count(&generationBenchmarkCount)
	h.DB.Model(&model.Problem{}).Where("is_translation_benchmark = ?", true).Count(&translationBenchmarkCount)
	h.DB.Model(&model.Submission{}).Count(&submissionCount)
	h.DB.Model(&model.GenCode{}).Count(&genCodeCount)
	h.DB.Model(&model.Translation{}).Count(&translationCount)

	type ModelStat struct {
		ModelName string  `json:"model_name"`
		Total     int64   `json:"total"`
		Accepted  int64   `json:"accepted"`
		ACRate    float64 `json:"ac_rate"`
	}
	var modelStats []ModelStat
	h.DB.Model(&model.Submission{}).
		Select("model_name, COUNT(*) as total, SUM(CASE WHEN ac_status = 'Accepted' THEN 1 ELSE 0 END) as accepted").
		Group("model_name").
		Find(&modelStats)
	for i := range modelStats {
		if modelStats[i].Total > 0 {
			modelStats[i].ACRate = float64(modelStats[i].Accepted) / float64(modelStats[i].Total) * 100
		}
	}

	var languages []string
	h.DB.Model(&model.Submission{}).Distinct("language").Pluck("language", &languages)

	c.JSON(http.StatusOK, gin.H{
		"problems":                       problemCount,
		"generation_benchmark_problems":  generationBenchmarkCount,
		"translation_benchmark_problems": translationBenchmarkCount,
		"submissions":                    submissionCount,
		"gen_codes":                      genCodeCount,
		"translations":                   translationCount,
		"models":                         modelStats,
		"languages":                      languages,
	})
}

// GetModelStats 返回指定模型的详细统计信息。
func (h *Handler) GetModelStats(c *gin.Context) {
	modelName := c.Param("model")

	type LangStat struct {
		Language string  `json:"language"`
		Total    int64   `json:"total"`
		Accepted int64   `json:"accepted"`
		ACRate   float64 `json:"ac_rate"`
	}
	var langStats []LangStat
	h.DB.Model(&model.Submission{}).
		Select("language, COUNT(*) as total, SUM(CASE WHEN ac_status = 'Accepted' THEN 1 ELSE 0 END) as accepted").
		Where("model_name = ?", modelName).
		Group("language").
		Find(&langStats)
	for i := range langStats {
		if langStats[i].Total > 0 {
			langStats[i].ACRate = float64(langStats[i].Accepted) / float64(langStats[i].Total) * 100
		}
	}

	var total, accepted int64
	h.DB.Model(&model.Submission{}).Where("model_name = ?", modelName).Count(&total)
	h.DB.Model(&model.Submission{}).Where("model_name = ? AND ac_status = ?", modelName, "Accepted").Count(&accepted)

	c.JSON(http.StatusOK, gin.H{
		"model":      modelName,
		"model_name": modelName,
		"total":      total,
		"accepted":   accepted,
		"ac_rate": func() float64 {
			if total > 0 {
				return float64(accepted) / float64(total) * 100
			}
			return 0
		}(),
		"languages": langStats,
	})
}

// GetCompletionStats 返回“模型 × 语言”在有效基准题上的完成率。
func (h *Handler) GetCompletionStats(c *gin.Context) {
	type completionRow struct {
		ModelName string  `json:"model_name"`
		Language  string  `json:"language"`
		Completed int64   `json:"completed"`
		Rate      float64 `json:"completion_rate"`
	}

	var benchmarkTotal int64
	h.DB.Model(&model.Problem{}).Where("is_generation_benchmark = ?", true).Count(&benchmarkTotal)

	var models []string
	h.DB.Model(&model.Submission{}).Distinct("model_name").Order("model_name").Pluck("model_name", &models)

	var languages []string
	h.DB.Model(&model.Submission{}).Distinct("language").Order("language").Pluck("language", &languages)

	rows := make([]completionRow, 0)
	if benchmarkTotal == 0 || len(models) == 0 || len(languages) == 0 {
		c.JSON(http.StatusOK, gin.H{
			"benchmark_total": benchmarkTotal,
			"models":          models,
			"languages":       languages,
			"rows":            rows,
		})
		return
	}

	type rawRow struct {
		ModelName string `gorm:"column:model_name"`
		Language  string `gorm:"column:language"`
		Completed int64  `gorm:"column:completed"`
	}

	var raw []rawRow
	h.DB.Raw(`
		SELECT s.model_name, s.language, COUNT(DISTINCT s.qid) AS completed
		FROM submissions s
		JOIN problems p ON p.qid = s.qid
		WHERE p.is_generation_benchmark = 1 AND s.ac_status = 'Accepted'
		GROUP BY s.model_name, s.language
	`).Scan(&raw)

	completedMap := make(map[string]int64, len(raw))
	for _, item := range raw {
		key := item.ModelName + "@@" + item.Language
		completedMap[key] = item.Completed
	}

	for _, modelName := range models {
		for _, language := range languages {
			key := modelName + "@@" + language
			completed := completedMap[key]
			rate := 0.0
			if benchmarkTotal > 0 {
				rate = float64(completed) / float64(benchmarkTotal) * 100
			}
			rows = append(rows, completionRow{
				ModelName: modelName,
				Language:  language,
				Completed: completed,
				Rate:      rate,
			})
		}
	}

	c.JSON(http.StatusOK, gin.H{
		"benchmark_total": benchmarkTotal,
		"models":          models,
		"languages":       languages,
		"rows":            rows,
	})
}

// GetPassKDashboard 返回 Dashboard 需要的 Pass@k 聚合数据。
func (h *Handler) GetPassKDashboard(c *gin.Context) {
	const benchmarkLanguageCount = 8
	const translationPairCount = benchmarkLanguageCount * (benchmarkLanguageCount - 1)

	var generationBenchmarkCount int64
	h.DB.Model(&model.Problem{}).Where("is_generation_benchmark = ?", true).Count(&generationBenchmarkCount)

	var translationBenchmarkCount int64
	h.DB.Model(&model.Problem{}).Where("is_translation_benchmark = ?", true).Count(&translationBenchmarkCount)

	generationModelDenominator := generationBenchmarkCount * benchmarkLanguageCount
	generationLanguageDenominator := generationBenchmarkCount
	translationPairDenominator := translationBenchmarkCount

	type generationModelRow struct {
		ModelName string  `gorm:"column:model_name" json:"model_name"`
		PassAt1   float64 `gorm:"column:pass_at_1" json:"pass_at_1"`
		PassAt2   float64 `gorm:"column:pass_at_2" json:"pass_at_2"`
		PassAt3   float64 `gorm:"column:pass_at_3" json:"pass_at_3"`
		PassAt4   float64 `gorm:"column:pass_at_4" json:"pass_at_4"`
		PassAt5   float64 `gorm:"column:pass_at_5" json:"pass_at_5"`
	}
	type generationLanguageRow struct {
		ModelName string  `gorm:"column:model_name" json:"model_name"`
		Language  string  `gorm:"column:language" json:"language"`
		PassAt1   float64 `gorm:"column:pass_at_1" json:"pass_at_1"`
		PassAt2   float64 `gorm:"column:pass_at_2" json:"pass_at_2"`
		PassAt3   float64 `gorm:"column:pass_at_3" json:"pass_at_3"`
		PassAt4   float64 `gorm:"column:pass_at_4" json:"pass_at_4"`
		PassAt5   float64 `gorm:"column:pass_at_5" json:"pass_at_5"`
	}
	type translationPairRow struct {
		ModelName string  `gorm:"column:model_name" json:"model_name"`
		SrcLang   string  `gorm:"column:src_lang" json:"src_lang"`
		TgtLang   string  `gorm:"column:tgt_lang" json:"tgt_lang"`
		PassAt1   float64 `gorm:"column:pass_at_1" json:"pass_at_1"`
		PassAt2   float64 `gorm:"column:pass_at_2" json:"pass_at_2"`
		PassAt3   float64 `gorm:"column:pass_at_3" json:"pass_at_3"`
		PassAt4   float64 `gorm:"column:pass_at_4" json:"pass_at_4"`
		PassAt5   float64 `gorm:"column:pass_at_5" json:"pass_at_5"`
	}

	var generationModels []generationModelRow
	if generationModelDenominator > 0 {
		h.DB.Model(&model.GenerationPassK{}).
			Select("model_name, SUM(pass_at_1) * 100 / ? AS pass_at_1, SUM(pass_at_2) * 100 / ? AS pass_at_2, SUM(pass_at_3) * 100 / ? AS pass_at_3, SUM(pass_at_4) * 100 / ? AS pass_at_4, SUM(pass_at_5) * 100 / ? AS pass_at_5",
				generationModelDenominator, generationModelDenominator, generationModelDenominator, generationModelDenominator, generationModelDenominator).
			Group("model_name").
			Order("model_name").
			Scan(&generationModels)
	}

	var generationLanguages []generationLanguageRow
	if generationLanguageDenominator > 0 {
		h.DB.Model(&model.GenerationPassK{}).
			Select("model_name, language, SUM(pass_at_1) * 100 / ? AS pass_at_1, SUM(pass_at_2) * 100 / ? AS pass_at_2, SUM(pass_at_3) * 100 / ? AS pass_at_3, SUM(pass_at_4) * 100 / ? AS pass_at_4, SUM(pass_at_5) * 100 / ? AS pass_at_5",
				generationLanguageDenominator, generationLanguageDenominator, generationLanguageDenominator, generationLanguageDenominator, generationLanguageDenominator).
			Group("model_name, language").
			Order("model_name, language").
			Scan(&generationLanguages)
	}

	var translationPairs []translationPairRow
	if translationPairDenominator > 0 {
		h.DB.Model(&model.TranslationPassK{}).
			Select("model_name, src_lang, tgt_lang, SUM(pass_at_1) * 100 / ? AS pass_at_1, SUM(pass_at_2) * 100 / ? AS pass_at_2, SUM(pass_at_3) * 100 / ? AS pass_at_3, SUM(pass_at_4) * 100 / ? AS pass_at_4, SUM(pass_at_5) * 100 / ? AS pass_at_5",
				translationPairDenominator, translationPairDenominator, translationPairDenominator, translationPairDenominator, translationPairDenominator).
			Group("model_name, src_lang, tgt_lang").
			Order("model_name, src_lang, tgt_lang").
			Scan(&translationPairs)
	}

	var generationModelsList []string
	h.DB.Model(&model.GenerationPassK{}).Distinct("model_name").Order("model_name").Pluck("model_name", &generationModelsList)

	var translationModelsList []string
	h.DB.Model(&model.TranslationPassK{}).Distinct("model_name").Order("model_name").Pluck("model_name", &translationModelsList)

	c.JSON(http.StatusOK, gin.H{
		"generation_models":       generationModels,
		"generation_languages":    generationLanguages,
		"translation_pairs":       translationPairs,
		"generation_model_names":  generationModelsList,
		"translation_model_names": translationModelsList,
		"benchmark_denominators": gin.H{
			"generation_model":    generationModelDenominator,
			"generation_language": generationLanguageDenominator,
			"translation_model":   translationBenchmarkCount * translationPairCount,
			"translation_pair":    translationPairDenominator,
		},
	})
}
