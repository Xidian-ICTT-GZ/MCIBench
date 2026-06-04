package handler

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/m1inato/mcibench-board/internal/model"
)

// ListProblems 返回分页题目列表。
func (h *Handler) ListProblems(c *gin.Context) {
	page, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	pageSize, _ := strconv.Atoi(c.DefaultQuery("page_size", "50"))
	search := c.Query("search")
	benchmark := strings.TrimSpace(c.Query("benchmark"))
	requireSubmission := false
	if raw := strings.TrimSpace(c.Query("require_submission")); raw != "" {
		parsed, err := strconv.ParseBool(raw)
		if err == nil {
			requireSubmission = parsed
		}
	}

	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 200 {
		pageSize = 50
	}
	offset := (page - 1) * pageSize

	query := h.DB.Model(&model.Problem{})
	if search != "" {
		query = query.Where("qid LIKE ? OR title LIKE ? OR slug LIKE ?",
			"%"+search+"%", "%"+search+"%", "%"+search+"%")
	}

	if requireSubmission {
		query = query.Where("qid IN (?)", h.DB.Model(&model.Submission{}).Select("DISTINCT qid"))
	}
	switch benchmark {
	case "generation":
		query = query.Where("is_generation_benchmark = ?", true)
	case "translation":
		query = query.Where("is_translation_benchmark = ?", true)
	case "", "all":
	default:
		c.JSON(http.StatusBadRequest, gin.H{"error": "benchmark must be all, generation, or translation"})
		return
	}

	var total int64
	query.Count(&total)

	var problems []model.Problem
	query.Order("qid").Offset(offset).Limit(pageSize).Find(&problems)

	c.JSON(http.StatusOK, gin.H{
		"data":               problems,
		"total":              total,
		"page":               page,
		"page_size":          pageSize,
		"require_submission": requireSubmission,
		"benchmark":          benchmark,
	})
}

// GetProblem 返回单个题目的详细信息及关联数据。
func (h *Handler) GetProblem(c *gin.Context) {
	qid := c.Param("qid")

	var problem model.Problem
	if err := h.DB.Where("qid = ?", qid).First(&problem).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "题目未找到"})
		return
	}

	var snippets []model.Snippet
	h.DB.Where("qid = ?", qid).Find(&snippets)

	var references []model.Reference
	h.DB.Where("qid = ?", qid).Find(&references)

	c.JSON(http.StatusOK, gin.H{
		"qid":                      strconv.Itoa(problem.QID),
		"tid":                      problem.TID,
		"title":                    problem.Title,
		"slug":                     problem.Slug,
		"url":                      problem.URL,
		"description":              problem.Description,
		"difficulty":               problem.Difficulty,
		"is_benchmark":             problem.IsBenchmark,
		"is_generation_benchmark":  problem.IsGenerationBenchmark,
		"is_translation_benchmark": problem.IsTranslationBenchmark,
		"created_at":               problem.CreatedAt,
		"updated_at":               problem.UpdatedAt,
		"snippets":                 snippets,
		"references":               references,
	})
}

// GetGenCode 返回指定题目的 LLM 生成代码。
func (h *Handler) GetGenCode(c *gin.Context) {
	qid := c.Param("qid")
	modelName := c.Query("model")
	language := c.Query("language")

	query := h.DB.Where("qid = ?", qid)
	if modelName != "" {
		query = query.Where("model_name = ?", modelName)
	}
	if language != "" {
		query = query.Where("language = ?", language)
	}

	var codes []model.GenCode
	query.Order("model_name, language, attempt_num").Find(&codes)

	c.JSON(http.StatusOK, gin.H{
		"data":  codes,
		"total": len(codes),
	})
}

// GetTranslations 返回指定题目的代码翻译结果。
func (h *Handler) GetTranslations(c *gin.Context) {
	qid := c.Param("qid")
	modelName := c.Query("model")
	srcLang := c.Query("src_lang")
	tgtLang := c.Query("tgt_lang")

	query := h.DB.Where("qid = ?", qid)
	if modelName != "" {
		query = query.Where("model_name = ?", modelName)
	}
	if srcLang != "" {
		query = query.Where("src_lang = ?", srcLang)
	}
	if tgtLang != "" {
		query = query.Where("tgt_lang = ?", tgtLang)
	}

	var translations []model.Translation
	query.Order("model_name, src_lang, tgt_lang, attempt_num").Find(&translations)

	c.JSON(http.StatusOK, gin.H{
		"data":  translations,
		"total": len(translations),
	})
}
