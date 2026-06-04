package handler

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/m1inato/mcibench-board/internal/model"
)

// ListSubmissions 返回按条件过滤的分页提交记录。
func (h *Handler) ListSubmissions(c *gin.Context) {
	page, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	pageSize, _ := strconv.Atoi(c.DefaultQuery("page_size", "50"))
	qid := c.Query("qid")
	modelName := c.Query("model")
	language := c.Query("language")
	status := c.Query("status")
	sourceType := c.Query("source_type")
	srcLang := c.Query("src_lang")
	tgtLang := c.Query("tgt_lang")

	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 500 {
		pageSize = 50
	}
	offset := (page - 1) * pageSize

	query := h.DB.Model(&model.Submission{})
	if qid != "" {
		query = query.Where("qid = ?", qid)
	}
	if modelName != "" {
		query = query.Where("model_name = ?", modelName)
	}
	if language != "" {
		query = query.Where("language = ?", language)
	}
	if status != "" {
		query = query.Where("ac_status = ?", status)
	}
	if sourceType != "" {
		query = query.Where("source_type = ?", sourceType)
	}
	if srcLang != "" {
		query = query.Where("src_lang = ?", srcLang)
	}
	if tgtLang != "" {
		query = query.Where("tgt_lang = ?", tgtLang)
	}

	var total int64
	query.Count(&total)

	var submissions []model.Submission
	query.Order("qid, source_type, model_name, language, src_lang, tgt_lang, attempt_num").
		Offset(offset).Limit(pageSize).Find(&submissions)

	c.JSON(http.StatusOK, gin.H{
		"data":      submissions,
		"total":     total,
		"page":      page,
		"page_size": pageSize,
	})
}
